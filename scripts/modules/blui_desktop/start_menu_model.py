# SPDX-License-Identifier: GPL-2.0-or-later
"""Small, pure Start-menu index and preference schema; never resolves launch targets."""
import hashlib
import ntpath
import os
import unicodedata

MAX_APPS = 1024
MAX_PINS = 64
MAX_RECENT = 24
MAX_BYTES = 8 * 1024 * 1024
SYSTEM_ACTIONS = {'FILES', 'SETTINGS', 'POWER_SETTINGS', 'LOCK', 'SHUTDOWN', 'RESTART'}


def text(value, maximum, *, empty=True):
    if (not isinstance(value, str) or len(value) > maximum or '\x00' in value or
            any(ord(char) < 32 for char in value) or (not empty and not value)):
        raise ValueError('Invalid Start menu text')
    return value


def relative_path(value):
    value = text(value, 2048, empty=False)
    parts = value.replace('/', '\\').split('\\')
    if (ntpath.isabs(value) or ntpath.splitdrive(value)[0] or
            any(part in {'', '.', '..'} or ':' in part for part in parts) or
            ntpath.splitext(parts[-1])[1].lower() not in {'.lnk', '.exe'}):
        raise ValueError('Invalid Start menu program path')
    return '\\'.join(parts)


def app_id(source, relative):
    if not isinstance(source, str) or source not in {'user', 'common'}:
        raise ValueError('Invalid Start menu program source')
    return hashlib.sha256((source + '\0' + relative_path(relative).casefold()).encode('utf-8')).hexdigest()


def key(value):
    if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
        raise ValueError('Invalid Start menu program identity')
    return value


def program(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid Start menu program')
    source, relative = value.get('source'), relative_path(value.get('relative'))
    identity = key(value.get('id'))
    if identity != app_id(source, relative):
        raise ValueError('Start menu program identity mismatch')
    path = text(value.get('path'), 4096, empty=False)
    if not (os.path.isabs(path) or ntpath.isabs(path)):
        raise ValueError('Invalid absolute Start menu path')
    signature = value.get('signature')
    if (not isinstance(signature, dict) or set(signature) != {'mtime_ns', 'size', 'device', 'inode'} or
            any(type(item) is not int or not 0 <= item < 1 << 128 for item in signature.values())):
        raise ValueError('Invalid Start menu file identity')
    return {'id': identity, 'source': source, 'relative': relative, 'path': path,
            'name': text(value.get('name'), 255, empty=False),
            'group': text(value.get('group', ''), 1024), 'signature': dict(signature)}


def state(value):
    if (not isinstance(value, dict) or value.get('version') != 1 or
            type(value.get('version')) is not int or type(value.get('revision')) is not int or
            not 0 <= value['revision'] < 1 << 63):
        raise ValueError('Invalid Start menu preferences')
    result = {'version': 1, 'revision': value['revision']}
    for field, maximum in (('pins', MAX_PINS), ('recent', MAX_RECENT)):
        items = value.get(field)
        if not isinstance(items, list) or len(items) > maximum:
            raise ValueError('Too many Start menu programs')
        items = [key(item) for item in items]
        if len(items) != len(set(items)):
            raise ValueError('Duplicate Start menu program')
        result[field] = items
    return result


def empty_state():
    return {'version': 1, 'revision': 0, 'pins': [], 'recent': []}


def validate_index(value):
    if (not isinstance(value, dict) or not isinstance(value.get('rows'), list) or
            len(value['rows']) > MAX_APPS or type(value.get('truncated')) is not bool):
        raise ValueError('Invalid Start menu index')
    rows = [program(row) for row in value['rows']]
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate Start menu index identity')
    errors = value.get('errors', [])
    if not isinstance(errors, list) or len(errors) > 32:
        raise ValueError('Invalid Start menu scan status')
    return dict(state(value), rows=rows, truncated=value['truncated'],
                errors=[text(error, 1024) for error in errors])


def folded(value):
    return unicodedata.normalize('NFKC', value).casefold()


def search(rows, query, *, maximum=MAX_APPS):
    """Bounded in-memory name/category matching; the query can NEVER become a command."""
    words = folded(text(query, 256)).split()
    if type(maximum) is not int or not 0 <= maximum <= MAX_APPS or len(rows) > MAX_APPS:
        raise ValueError('Invalid Start menu search size')
    matched = [row for row in rows if all(word in folded(row['name'] + ' ' + row['group']) for word in words)]
    matched.sort(key=lambda row: (not folded(row['name']).startswith(' '.join(words)),
                                 folded(row['name']), folded(row['group']), row['id']))
    return matched[:maximum]


def selected(rows, keys):
    by_id = {row['id']: row for row in rows}
    return [by_id[identity] for identity in keys if identity in by_id]
