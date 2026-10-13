# SPDX-License-Identifier: GPL-2.0-or-later
"""Deterministic weather/cache tests: no network or user's config/files accessed."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib import parse

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts' / 'modules'))
from blui_desktop import weather


def payload():
    return {'timezone': 'Asia/Shanghai',
            'current_units': {'temperature_2m': '°C', 'wind_speed_10m': 'km/h'},
            'current': {'time': '2026-10-13T10:30', 'temperature_2m': 24.1,
                        'relative_humidity_2m': 68, 'weather_code': 0,
                        'wind_speed_10m': 9.9, 'is_day': 1}}


def data(now=10000):
    return weather.normalize(payload(), 30.2741, 120.1551, now=now)


class Response:
    def __init__(self, body):
        self.body, self.read_limit = body, None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit):
        self.read_limit = limit
        return self.body[:limit]


class DesktopWeather(unittest.TestCase):
    def test_fetch_only_sends_explicit_coordinates_to_fixed_https_origin(self):
        response = Response(json.dumps(payload()).encode('utf-8'))
        opener = mock.Mock(return_value=response)
        result = weather.fetch(30.2741, 120.1551, 'CMA', now=10000, opener=opener)
        req = opener.call_args.args[0]
        url = parse.urlsplit(req.full_url)
        self.assertEqual((url.scheme, url.hostname, url.path),
                         ('https', 'api.open-meteo.com', '/v1/forecast'))
        query = parse.parse_qs(url.query)
        self.assertEqual(query['models'], ['cma_grapes_global'])
        self.assertEqual(query['latitude'], ['30.2741'])
        self.assertEqual(query['longitude'], ['120.1551'])
        self.assertNotIn('city', query)
        self.assertNotIn('apikey', query)
        self.assertEqual(opener.call_args.kwargs['timeout'], weather.TIMEOUT)
        self.assertEqual(response.read_limit, weather.MAX_BYTES + 1)
        self.assertEqual(result['condition'], 'Clear sky')
        self.assertEqual(result['updated_at'], '1970-01-01T02:46:40+00:00')
        self.assertIn('CC BY', result['attribution'])

    def test_invalid_config_is_rejected_before_any_network_request(self):
        for args in ((91, 0), (0, -181), (True, 2), (0, float('nan')),
                     (0, float('inf')), ('30', 120), (0, 0, []),
                     (0, 0, 'https://localhost/private')):
            with self.subTest(args=args):
                opener = mock.Mock(side_effect=AssertionError('No network'))
                with self.assertRaises(weather.WeatherError):
                    weather.fetch(*args, opener=opener)
                opener.assert_not_called()

    def test_response_types_units_timestamps_and_size_are_bounded(self):
        cases = []
        for field, value in (('temperature_2m', True), ('temperature_2m', float('nan')),
                             ('relative_humidity_2m', 101), ('weather_code', True),
                             ('wind_speed_10m', '9'), ('time', 'bad'), ('is_day', 2)):
            item = payload()
            item['current'][field] = value
            cases.append(item)
        item = payload()
        item['current_units']['temperature_2m'] = '°F'
        cases.extend((item, [], {'error': True}, {'current': {}}))
        for item in cases:
            with self.subTest(item=item):
                with self.assertRaises(weather.WeatherError):
                    weather.normalize(item, 30.2741, 120.1551)
        for encoded in (b'{bad', b'\xff', b' ' * (weather.MAX_BYTES + 1),
                        ('[' * 10000).encode('ascii')):
            with self.subTest(length=len(encoded)):
                with self.assertRaises(weather.WeatherError):
                    weather.fetch(30.2741, 120.1551,
                                  opener=mock.Mock(return_value=Response(encoded)))

    def test_foreign_or_unencrypted_redirects_are_blocked(self):
        redirect = weather._SameOriginRedirect()
        for target in ('http://api.open-meteo.com/', 'https://localhost/',
                       'https://api.open-meteo.com.evil.test/',
                       'https://user:password@api.open-meteo.com/',
                       'https://api.open-meteo.com:444/'):
            with self.subTest(target=target):
                with self.assertRaises(weather.WeatherError):
                    redirect.redirect_request(None, None, 302, '', {}, target)

    def test_atomic_cache_and_fresh_cache_avoid_network_requests(self):
        with tempfile.TemporaryDirectory(prefix='blui_weather_') as directory:
            first = data()
            weather.save_cache(directory, first)
            target = Path(directory) / weather.cache_key(30.2741, 120.1551)
            self.assertFalse(target.read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertEqual(weather.read_cache(directory, 30.2741, 120.1551), first)
            fetcher = mock.Mock(side_effect=AssertionError('Fresh cache must not network'))
            result = weather.refresh(30.2741, 120.1551, directory, now=10001, fetcher=fetcher)
            self.assertEqual(result['data'], first)
            self.assertTrue(result['cached'])
            self.assertFalse(result['stale'])
            fetcher.assert_not_called()
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_stale_offline_cache_is_kept_and_reports_original_update_time(self):
        with tempfile.TemporaryDirectory(prefix='blui_weather_offline_') as directory:
            first = data()
            weather.save_cache(directory, first)
            fetcher = mock.Mock(side_effect=TimeoutError('Fixture offline'))
            result = weather.refresh(30.2741, 120.1551, directory,
                                     now=20000, fetcher=fetcher)
            self.assertTrue(result['stale'])
            self.assertEqual(result['data'], first)
            self.assertEqual(result['error'], 'Offline weather cache')
            self.assertEqual(weather.read_cache(directory, 30.2741, 120.1551), first)
            no_cache = weather.refresh(0, 0, directory, now=20000, fetcher=fetcher)
            self.assertIsNone(no_cache['data'])
            self.assertFalse(no_cache['stale'])
            self.assertEqual(no_cache['error'], 'Weather service is unavailable')

    def test_force_refresh_replaces_only_matching_location_provider_cache(self):
        with tempfile.TemporaryDirectory(prefix='blui_weather_force_') as directory:
            weather.save_cache(directory, data())
            newer = data(10001)
            newer['temperature'] = 23.5
            fetcher = mock.Mock(return_value=newer)
            result = weather.refresh(30.2741, 120.1551, directory, force=True,
                                     now=10001, fetcher=fetcher)
            self.assertFalse(result['cached'])
            self.assertEqual(result['data']['temperature'], 23.5)
            fetcher.assert_called_once()
            self.assertIsNone(weather.read_cache(directory, 31, 120.1551))
            self.assertIsNone(weather.read_cache(directory, 30.2741, 120.1551, 'CMA'))
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_corrupt_or_incomplete_cache_is_never_presented_as_new_weather(self):
        with tempfile.TemporaryDirectory(prefix='blui_weather_corrupt_') as directory:
            target = Path(directory) / weather.cache_key(30.2741, 120.1551)
            for variant in (b'{bad', b' ' * (weather.MAX_BYTES + 1), b'[]'):
                target.write_bytes(variant)
                self.assertIsNone(weather.read_cache(directory, 30.2741, 120.1551))
            for field in ('fetched_at', 'code', 'temperature', 'version'):
                bad = copy.deepcopy(data())
                del bad[field]
                target.write_text(json.dumps(bad), encoding='utf-8')
                self.assertIsNone(weather.read_cache(directory, 30.2741, 120.1551))

    def test_cache_write_failure_keeps_fresh_result_available(self):
        with tempfile.TemporaryDirectory(prefix='blui_weather_cache_failure_') as directory:
            with mock.patch.object(weather, 'save_cache', side_effect=PermissionError('Fixture denied')):
                result = weather.refresh(30.2741, 120.1551, directory,
                                         now=10000, fetcher=mock.Mock(return_value=data()))
            self.assertEqual(result['data']['temperature'], 24.1)
            self.assertFalse(result['stale'])
            self.assertEqual(result['error'], 'Weather cache could not be saved')


if __name__ == '__main__':
    unittest.main(verbosity=2)
