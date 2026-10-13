# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure validation of bounded notification-host snapshots and explicit callbacks."""
import base64
import hashlib
import uuid

MAX_BYTES = 4 * 1024 * 1024
MAX_COMMANDS = 32
MAX_ICONS = 128
PREFIX = 'blui-notification:'
EVENTS = {'LEFT', 'RIGHT', 'DOUBLE', 'HOVER_ENTER', 'HOVER_LEAVE'}
FIELDS = {'key', 'handle', 'uid', 'guid', 'callback', 'version', 'tip', 'hidden', 'width',
          'height', 'rgba', 'pid', 'thread_id', 'process_started', 'window_class'}


def _text(value, maximum, *, empty=True):
    if (not isinstance(value, str) or len(value) > maximum or '\x00' in value or
            (not empty and not value)):
        raise ValueError('Invalid notification text')
    return value


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid notification integer')
    return value


def _decimal(value, *, zero=False):
    value = _text(value, 20, empty=False)
    if not value.isascii() or not value.isdigit() or not (0 if zero else 1) <= int(value) < 1 << 64:
        raise ValueError('Invalid notification window identity')
    return value


def empty(error=''):
    return {'enabled': False, 'error': error[:1024], 'revision': 0, 'host_handle': '0', 'icons': []}


def validate_snapshot(value):
    """Return metadata and prepared preview rows; no bpy, native APIs or I/O."""
    if (not isinstance(value, dict) or set(value) != set(empty()) or
            type(value['enabled']) is not bool or not isinstance(value['icons'], list) or
            len(value['icons']) > MAX_ICONS):
        raise ValueError('Invalid notification snapshot')
    result = {'enabled': value['enabled'], 'error': _text(value['error'], 1024),
              'revision': _integer(value['revision'], 0, (1 << 63) - 1),
              'host_handle': _decimal(value['host_handle'], zero=not value['enabled']), 'icons': []}
    if not value['enabled'] and value['icons']:
        raise ValueError('Disabled notification host cannot expose actions')
    previews, identities = {}, set()
    for row in value['icons']:
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError('Invalid notification icon')
        handle = _decimal(row['handle'])
        uid = _integer(row['uid'], 0, 0xffffffff)
        guid = _text(row['guid'], 36)
        if guid and str(uuid.UUID(guid)) != guid:
            raise ValueError('Invalid notification GUID')
        expected = 'guid:' + guid if guid else 'hwnd:' + str(int(handle)) + ':' + str(uid)
        if row['key'] != expected or expected in identities:
            raise ValueError('Invalid or duplicate notification icon identity')
        identities.add(expected)
        callback = _integer(row['callback'], 0, 0xffff)
        if callback and callback < 0x400:
            raise ValueError('Invalid notification callback')
        _integer(row['version'], 0, 4)
        _integer(row['pid'], 1, 0xffffffff)
        _integer(row['thread_id'], 1, 0xffffffff)
        _decimal(row['process_started'])
        _text(row['window_class'], 256, empty=False)
        _text(row['tip'], 127)
        if type(row['hidden']) is not bool:
            raise ValueError('Invalid notification visibility')
        width = _integer(row['width'], 0, 32)
        height = _integer(row['height'], 0, 32)
        if (width, height) not in {(0, 0), (32, 32)}:
            raise ValueError('Invalid notification icon size')
        rgba = _text(row['rgba'], 5500)
        raw = base64.b64decode(rgba, validate=True)
        if len(raw) != width * height * 4:
            raise ValueError('Invalid notification pixels')
        metadata = {name: item for name, item in row.items() if name not in {'width', 'height', 'rgba'}}
        metadata['cache_key'] = ''
        if width:
            digest = hashlib.sha256(bytes((width, height)) + raw).hexdigest()
            metadata['cache_key'] = PREFIX + digest
            previews[metadata['cache_key']] = {'path': metadata['cache_key'], 'width': width,
                                              'height': height, 'rgba': rgba}
        result['icons'].append(metadata)
    return result, previews


def callback(key, event, x, y, value):
    if not value.get('enabled') or event not in EVENTS:
        raise ValueError('Notification area is unavailable')
    row = next((row for row in value['icons'] if row['key'] == key), None)
    if row is None or not row['callback']:
        raise ValueError('This notification icon changed or exited')
    _integer(x, -32768, 32767)
    _integer(y, -32768, 32767)
    return {'command': 'activate', 'key': row['key'], 'event': event, 'x': x, 'y': y}
