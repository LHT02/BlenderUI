# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded filesystem snapshots and portable canvas layouts; no bpy dependency."""
import json
import math
import os
from pathlib import Path
import tempfile
import time
from contextlib import contextmanager

LIMIT = 1000
MAX_BYTES = 8 * 1024 * 1024
TREE = 'BLUIDesktopTree'
FILE = 'BLUIDesktopFile'
NOTE = 'BLUIDesktopNote'
GROUP = 'BLUIDesktopGroup'
FRAME = 'NodeFrame'
CLOCK = 'BLUIDesktopClock'
CALCULATOR = 'BLUIDesktopCalculator'
WEATHER = 'BLUIDesktopWeather'


def scan(directory):
    rows = []
    truncated = False
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(rows) == LIMIT:
                truncated = True
                break
            try:
                folder = entry.is_dir(follow_symlinks=False)
            except OSError:
                folder = False
            rows.append({'path': entry.path, 'name': entry.name, 'folder': folder})
    rows.sort(key=lambda row: (not row['folder'], row['name'].casefold()))
    return {'rows': rows, 'truncated': truncated}


def inspect_paths(paths):
    """Only inspect explicitly supplied cards; never recurse, resolve links, or expand folders."""
    if not isinstance(paths, (list, tuple)) or len(paths) > LIMIT:
        raise ValueError('Too many desktop paths')
    rows, seen = [], set()
    for value in paths:
        if not isinstance(value, str) or not value or len(value) > 32768 or '\x00' in value:
            raise ValueError('Invalid desktop path')
        path = os.path.abspath(value)
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        rows.append({'path': path, 'name': os.path.basename(os.path.normpath(path)) or path,
                     'folder': os.path.isdir(path)})
    return rows


def _text(value, maximum=32768):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ValueError('Invalid canvas text')
    return value


def _number(value, low, high):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError('Invalid canvas value')
    return value


def background(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid desktop background')
    mode = value.get('fit', 'FILL')
    if not isinstance(mode, str) or mode not in {'FIT', 'FILL', 'STRETCH', 'CENTER', 'TILE', 'SPAN'}:
        raise ValueError('Invalid background layout')
    enabled = value.get('enabled', False)
    if type(enabled) is not bool:
        raise ValueError('Invalid background flag')
    return {'path': _text(value.get('path', '')), 'enabled': enabled, 'fit': mode,
            'opacity': _number(value.get('opacity', 1), 0, 1),
            'align_x': _number(value.get('align_x', 0), -1, 1),
            'align_y': _number(value.get('align_y', 0), -1, 1)}


def validate(payload):
    if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] not in {1, 2}:
        raise ValueError('Unsupported canvas layout')
    rows = payload.get('nodes')
    if not isinstance(rows, list) or len(rows) > LIMIT:
        raise ValueError('Canvas contains too many cards')
    def clean_rows(rows):
        if not isinstance(rows, list) or len(rows) > LIMIT:
            raise ValueError('Canvas contains too many cards')
        clean, seen = [], set()
        for row in rows:
            item = clean_row(row)
            if 'id' in item:
                if item['id'] in seen:
                    raise ValueError('Duplicate desktop card identity')
                seen.add(item['id'])
            clean.append(item)
        by_id = {row['id']: row for row in clean if 'id' in row}
        for row in clean:
            parent = row.get('parent')
            if parent and (parent not in by_id or by_id[parent]['kind'] != FRAME):
                raise ValueError('Invalid icon panel parent')
        for row in clean:
            chain = set()
            current = row
            while current.get('parent'):
                parent = current['parent']
                if parent in chain or len(chain) >= 16:
                    raise ValueError('Recursive icon panel')
                chain.add(parent)
                current = by_id[parent]
        return clean

    def clean_row(row):
        if (not isinstance(row, dict) or not isinstance(row.get('kind'), str) or
            row['kind'] not in {FILE, NOTE, FRAME, GROUP, CLOCK, CALCULATOR, WEATHER}):
            raise ValueError('Invalid canvas card')
        location = row.get('location')
        if not isinstance(location, (list, tuple)) or len(location) != 2 or not all(
                type(value) in (int, float) and abs(value) <= 1e7 and math.isfinite(value)
                for value in location):
            raise ValueError('Invalid canvas position')
        item = {'kind': row['kind'], 'location': list(location)}
        for field in ('path', 'name', 'note'):
            item[field] = _text(row.get(field, ''))
        if type(row.get('folder', False)) is not bool:
            raise ValueError('Invalid canvas folder flag')
        item['folder'] = row.get('folder', False)
        for key in ('id', 'parent'):
            value = row.get(key)
            if value is not None:
                if not isinstance(value, str) or len(value) != 32 or any(char not in '0123456789abcdef' for char in value):
                    raise ValueError('Invalid desktop card identity')
                item[key] = value
        props = row.get('props', {})
        if not isinstance(props, dict):
            raise ValueError('Invalid desktop properties')
        item['props'] = {'width': _number(props.get('width', 120 if row['kind'] == FILE else 260), 80, 100000 if row['kind'] == FRAME else 3000)}
        if row['kind'] == FRAME:
            item['props']['height'] = _number(props.get('height', 200), 1, 100000)
            item['props']['label_size'] = int(_number(props.get('label_size', 20), 8, 64))
            if type(props.get('shrink', True)) is not bool:
                raise ValueError('Invalid panel flag')
            item['props']['shrink'] = props.get('shrink', True)
        elif row['kind'] == CLOCK:
            for key, default in (('clock_format', '%H:%M:%S'), ('date_format', '%Y-%m-%d')):
                item['props'][key] = _text(props.get(key, default), 64)
        elif row['kind'] == CALCULATOR:
            item['props']['expression'] = _text(props.get('expression', ''), 512)
        elif row['kind'] == WEATHER:
            item['props'].update(city=_text(props.get('city', 'Hangzhou'), 128),
                latitude=_number(props.get('latitude', 30.2741), -90, 90),
                longitude=_number(props.get('longitude', 120.1551), -180, 180))
            source = props.get('weather_source', 'AUTO')
            if not isinstance(source, str) or source not in {'AUTO', 'CMA'} or type(props.get('weather_enabled', False)) is not bool:
                raise ValueError('Invalid weather preference')
            item['props'].update(weather_source=source, weather_enabled=props.get('weather_enabled', False))
        if row['kind'] == GROUP:
            key = row.get('group')
            if key is not None and (not isinstance(key, str) or not key or len(key) > 32):
                raise ValueError('Invalid desktop group identity')
            item['group'] = key
        return item

    clean = clean_rows(rows)
    records, by_id, total = [], {}, len(clean)
    source_groups = payload.get('groups', [])
    if not isinstance(source_groups, list) or len(source_groups) > LIMIT:
        raise ValueError('Invalid desktop groups')
    for group in source_groups:
        if not isinstance(group, dict):
            raise ValueError('Invalid desktop group')
        key = _text(group.get('id'), 32)
        if not key or key in by_id:
            raise ValueError('Invalid desktop group identity')
        record = {'id': key, 'name': _text(group.get('name', ''), 255),
                  'directory': _text(group.get('directory', '')), 'nodes': clean_rows(group.get('nodes'))}
        total += len(record['nodes'])
        by_id[key] = record
        records.append(record)
    if total > LIMIT:
        raise ValueError('Desktop group contains too many cards')
    visited, heights = set(), {}
    def height(rows, ancestors):
        result = 0
        for row in rows:
            key = row.get('group')
            if key is None:
                continue
            if key not in by_id or key in ancestors or len(ancestors) >= 16:
                raise ValueError('Invalid recursive desktop group')
            visited.add(key)
            if key not in heights:
                heights[key] = height(by_id[key]['nodes'], ancestors | {key})
            result = max(result, 1 + heights[key])
            if result >= 16:
                raise ValueError('Desktop group is too deeply nested')
        return result
    height(clean, set())
    if len(visited) != len(by_id):
        raise ValueError('Unreachable desktop group')
    result = {'version': 2, 'directory': _text(payload.get('directory', '')), 'nodes': clean,
              'groups': records}
    if 'background' in payload:
        result['background'] = background(payload['background'])
    return result


def _encoded(payload):
    data = json.dumps(validate(payload), ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(data) > MAX_BYTES:
        raise ValueError('Canvas layout is too large')
    return data


def _read(target):
    with target.open('rb') as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Canvas layout is too large')
    return validate(json.loads(data.decode('utf-8')))


def _publish(target, data):
    descriptor, name = tempfile.mkstemp(prefix=target.name + '.', suffix='.tmp', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _save_lock(target):
    """Serialize save helpers; an exited/killed process releases its OS lock automatically."""
    with target.with_suffix('.lock').open('a+b') as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        if os.name == 'nt':
            import msvcrt
            acquire = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        deadline = time.monotonic() + 2.0
        while True:
            lock.seek(0)
            try:
                acquire()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Canvas is being saved by another desktop job')
                time.sleep(.02)
        try:
            yield
        finally:
            lock.seek(0)
            release()


def save(path, payload):
    data = _encoded(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _save_lock(target):
        try:
            previous = _encoded(_read(target))
        except (OSError, ValueError, UnicodeError):
            previous = None
        # Never overwrite the last valid backup with a corrupt current layout.
        if previous is not None:
            _publish(target.with_suffix('.bak'), previous)
        _publish(target, data)
    return str(target)


def load(path):
    target = Path(path)
    try:
        return _read(target)
    except (OSError, ValueError, UnicodeError) as error:
        try:
            return _read(target.with_suffix('.bak'))
        except (OSError, ValueError, UnicodeError):
            raise error
