# SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in Open-Meteo weather for isolated helpers, with bounded offline caching.

Sources: https://open-meteo.com/en/docs and /en/docs/cma-api. Current values
are model estimates, not station observations. Free hosted API is non-commercial
with CC-BY attribution: https://open-meteo.com/en/terms. Never locate the user by
IP/GPS, accept arbitrary URLs or run this module from UI draw/update callbacks.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from urllib import error, parse, request

HOST = 'api.open-meteo.com'
MAX_BYTES = 65536
REFRESH_SECONDS = 15 * 60
TIMEOUT = 6
SOURCES = {'AUTO', 'CMA'}
ATTRIBUTION = 'Open-Meteo · CC BY 4.0'
CITIES = (
    ('HANGZHOU', 'Hangzhou', 30.2741, 120.1551),
    ('BEIJING', 'Beijing', 39.9042, 116.4074),
    ('SHANGHAI', 'Shanghai', 31.2304, 121.4737),
    ('GUANGZHOU', 'Guangzhou', 23.1291, 113.2644),
    ('SHENZHEN', 'Shenzhen', 22.5431, 114.0579),
    ('CHENGDU', 'Chengdu', 30.5728, 104.0668),
    ('HONG_KONG', 'Hong Kong', 22.3193, 114.1694),
)


class WeatherError(ValueError):
    """Generic readable status which does not expose paths or requested locations."""


def coordinates(latitude, longitude, source='AUTO'):
    if not isinstance(source, str) or source not in SOURCES:
        raise WeatherError('Unsupported weather source')
    if (type(latitude) not in (float, int) or type(longitude) not in (float, int) or
            not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or
            not math.isfinite(latitude) or not math.isfinite(longitude)):
        raise WeatherError('Invalid weather coordinates')
    return round(float(latitude), 4), round(float(longitude), 4)


def _timestamp(value):
    if type(value) not in (int, float) or not 0 <= value <= 32503680000:
        raise WeatherError('Invalid weather timestamp')
    return float(value)


def condition(code):
    # Aggregate WMO codes into short, localizable card descriptions.
    if code == 0:
        return 'Clear sky'
    if code in (1, 2):
        return 'Partly cloudy'
    if code == 3:
        return 'Overcast'
    if code in (45, 48):
        return 'Fog'
    if code in (51, 53, 55, 56, 57):
        return 'Drizzle'
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return 'Rain'
    if code in (71, 73, 75, 77, 85, 86):
        return 'Snow'
    if code in (95, 96, 97, 99):
        return 'Thunderstorm'
    return 'Unknown weather'


def _numeric(value, minimum, maximum):
    if type(value) not in (int, float) or not minimum <= value <= maximum or not math.isfinite(value):
        raise WeatherError('Invalid weather response')
    return float(value)


def _text(value, limit=64):
    if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 for char in value):
        raise WeatherError('Invalid weather response')
    return value


def normalize(payload, latitude, longitude, source='AUTO', now=None):
    """Strictly validate upstream data into a small stable cache/IPC payload."""
    latitude, longitude = coordinates(latitude, longitude, source)
    if not isinstance(payload, dict) or payload.get('error'):
        raise WeatherError('Invalid weather response')
    current, units = payload.get('current'), payload.get('current_units')
    if not isinstance(current, dict) or not isinstance(units, dict):
        raise WeatherError('Invalid weather response')
    if units.get('temperature_2m') != '°C' or units.get('wind_speed_10m') != 'km/h':
        raise WeatherError('Invalid weather response')
    code, is_day = current.get('weather_code'), current.get('is_day')
    if type(code) is not int or not 0 <= code <= 99 or type(is_day) is not int or is_day not in (0, 1):
        raise WeatherError('Invalid weather response')
    observed_at = _text(current.get('time'), 32)
    try:
        if 'T' not in observed_at:
            raise ValueError('Missing date')
        datetime.fromisoformat(observed_at)
    except ValueError:
        raise WeatherError('Invalid weather response') from None
    fetched_at = _timestamp(time.time() if now is None else now)
    return {'version': 1, 'latitude': latitude, 'longitude': longitude, 'source': source,
            'temperature': _numeric(current.get('temperature_2m'), -150, 100),
            'humidity': _numeric(current.get('relative_humidity_2m'), 0, 100),
            'wind_speed': _numeric(current.get('wind_speed_10m'), 0, 500),
            'code': code, 'is_day': is_day, 'condition': condition(code),
            'observed_at': observed_at, 'timezone': _text(payload.get('timezone', 'UTC')),
            'fetched_at': fetched_at,
            'updated_at': datetime.fromtimestamp(fetched_at, timezone.utc).isoformat(timespec='seconds'),
            'attribution': ATTRIBUTION}


class _SameOriginRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = parse.urlsplit(newurl)
        if (target.scheme != 'https' or target.hostname != HOST or target.username or
                target.password or target.port not in (None, 443)):
            raise WeatherError('Weather service redirect was blocked')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(latitude, longitude, source='AUTO', *, timeout=TIMEOUT, now=None, opener=None):
    """One HTTPS request; helper lifetime also has an outer timeout in client.py."""
    latitude, longitude = coordinates(latitude, longitude, source)
    timeout = _numeric(timeout, .1, 10)
    params = {'latitude': latitude, 'longitude': longitude, 'timezone': 'auto',
              'current': 'temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,is_day',
              'temperature_unit': 'celsius', 'wind_speed_unit': 'kmh', 'forecast_days': 1}
    if source == 'CMA':
        params['models'] = 'cma_grapes_global'
    url = 'https://' + HOST + '/v1/forecast?' + parse.urlencode(params)
    req = request.Request(url, headers={'User-Agent': 'BLUI-Desktop/1.0 (github.com/LHT02/BlenderUI)',
                                        'Accept': 'application/json'})
    opener = opener or request.build_opener(_SameOriginRedirect()).open
    try:
        with opener(req, timeout=timeout) as response:
            encoded = response.read(MAX_BYTES + 1)
        if len(encoded) > MAX_BYTES:
            raise WeatherError('Weather response is too large')
        payload = json.loads(encoded)
    except WeatherError:
        raise
    except (error.URLError, OSError, TimeoutError):
        raise WeatherError('Weather service is unavailable') from None
    except (ValueError, RecursionError, UnicodeError):
        raise WeatherError('Invalid weather response') from None
    return normalize(payload, latitude, longitude, source, now)


def cache_key(latitude, longitude, source='AUTO'):
    latitude, longitude = coordinates(latitude, longitude, source)
    data = json.dumps([latitude, longitude, source], separators=(',', ':')).encode('ascii')
    return 'weather-' + hashlib.sha256(data).hexdigest()[:32] + '.json'


def _validate_cache(data, latitude, longitude, source):
    if (not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1 or
            data.get('latitude') != latitude or data.get('longitude') != longitude or
            data.get('source') != source):
        raise WeatherError('Invalid weather cache')
    payload = {'current': {'temperature_2m': data.get('temperature'),
                          'relative_humidity_2m': data.get('humidity'),
                          'wind_speed_10m': data.get('wind_speed'), 'weather_code': data.get('code'),
                          'is_day': data.get('is_day'), 'time': data.get('observed_at')},
               'current_units': {'temperature_2m': '°C', 'wind_speed_10m': 'km/h'},
               'timezone': data.get('timezone')}
    return normalize(payload, latitude, longitude, source, _timestamp(data.get('fetched_at')))


def read_cache(directory, latitude, longitude, source='AUTO'):
    """Read only the exact provider/location cache, never scan or follow layout paths."""
    latitude, longitude = coordinates(latitude, longitude, source)
    target = Path(directory) / cache_key(latitude, longitude, source)
    try:
        with target.open('rb') as saved:
            encoded = saved.read(MAX_BYTES + 1)
        if len(encoded) > MAX_BYTES:
            return None
        return _validate_cache(json.loads(encoded), latitude, longitude, source)
    except (OSError, ValueError, RecursionError, UnicodeError):
        return None


def save_cache(directory, data):
    """Atomic same-directory replace; only writes the dedicated weather cache key."""
    if not isinstance(data, dict):
        raise WeatherError('Invalid weather cache')
    latitude, longitude = coordinates(data.get('latitude'), data.get('longitude'), data.get('source'))
    data = _validate_cache(data, latitude, longitude, data['source'])
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise WeatherError('Weather cache is too large')
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / cache_key(latitude, longitude, data['source'])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=target.name + '.', suffix='.tmp',
                                         dir=folder, delete=False) as saved:
            temporary = saved.name
            saved.write(encoded)
            saved.flush()
            os.fsync(saved.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def refresh(latitude, longitude, cache_directory, source='AUTO', *, force=False, now=None, fetcher=None):
    """Return fresh/cached weather or an offline fallback without destroying old data.

    No exceptions for ordinary network/cache failures. Invalid configuration still
    raises WeatherError so a malformed task cannot issue any network request.
    """
    latitude, longitude = coordinates(latitude, longitude, source)
    now = _timestamp(time.time() if now is None else now)
    previous = read_cache(cache_directory, latitude, longitude, source)
    if previous and not force and 0 <= now - previous['fetched_at'] < REFRESH_SECONDS:
        return {'data': previous, 'cached': True, 'stale': False, 'error': ''}
    try:
        data = (fetcher or fetch)(latitude, longitude, source, now=now)
        data = _validate_cache(data, latitude, longitude, source)
    except (WeatherError, OSError, TimeoutError):
        return {'data': previous, 'cached': bool(previous), 'stale': bool(previous),
                'error': 'Offline weather cache' if previous else 'Weather service is unavailable'}
    status = ''
    try:
        save_cache(cache_directory, data)
    except (OSError, WeatherError):
        status = 'Weather cache could not be saved'
    return {'data': data, 'cached': False, 'stale': False, 'error': status}
