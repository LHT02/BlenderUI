# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure validation of bounded notification-host snapshots and explicit callbacks."""
import base64
import hashlib
import uuid
from . import notification_system

MAX_BYTES = 4 * 1024 * 1024
MAX_COMMANDS = 32
MAX_ICONS = 128
PREFIX = 'blui-notification:'
EVENTS = {'LEFT', 'RIGHT', 'DOUBLE', 'HOVER_ENTER', 'HOVER_LEAVE'}
FIELDS = {'key', 'handle', 'uid', 'guid', 'callback', 'version', 'tip', 'hidden', 'width',
          'height', 'rgba', 'pid', 'thread_id', 'process_started', 'window_class'}
OPTIONAL_HEADER = {'controls', 'platform', 'bootstrap'}
TOOLBAR_FIELDS = {'button_rect', 'toolbar_handle', 'toolbar_thread', 'overflow_handle', 'overflow_thread'}
OPTIONAL_ICON = {'backend', 'actions'} | TOOLBAR_FIELDS


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
    if (not isinstance(value, dict) or not set(empty()) <= set(value) or
            set(value) - set(empty()) - OPTIONAL_HEADER or
            type(value['enabled']) is not bool or not isinstance(value['icons'], list) or
            len(value['icons']) > MAX_ICONS):
        raise ValueError('Invalid notification snapshot')
    result = {'enabled': value['enabled'], 'error': _text(value['error'], 1024),
              'revision': _integer(value['revision'], 0, (1 << 63) - 1),
              'host_handle': _decimal(value['host_handle'], zero=not value['enabled']), 'icons': []}
    if not value['enabled'] and value['icons']:
        raise ValueError('Disabled notification host cannot expose actions')
    if 'platform' in value:
        result['platform'] = _integer(value['platform'], 0, 0xffffffff)
    if 'controls' in value:
        result['controls'] = notification_system.validate_controls(value['controls'])
        if result['controls'] and (not value['enabled'] or result.get('platform', 0) < 10240):
            raise ValueError('Disabled or unsupported host cannot expose system controls')
    if 'bootstrap' in value:
        item = value['bootstrap']
        if (not isinstance(item, dict) or set(item) != {'state', 'count', 'error'} or
                item['state'] not in {'DISABLED', 'LOADING', 'READY', 'PARTIAL', 'UNAVAILABLE'}):
            raise ValueError('Invalid notification bootstrap status')
        result['bootstrap'] = {'state': item['state'], 'count': _integer(item['count'], 0, MAX_ICONS),
                               'error': _text(item['error'], 256)}
    previews, identities = {}, set()
    for row in value['icons']:
        if (not isinstance(row, dict) or not FIELDS <= set(row) or set(row) - FIELDS - OPTIONAL_ICON):
            raise ValueError('Invalid notification icon')
        handle = _decimal(row['handle'])
        uid = _integer(row['uid'], 0, 0xffffffff)
        guid = _text(row['guid'], 36)
        if guid and str(uuid.UUID(guid)) != guid:
            raise ValueError('Invalid notification GUID')
        expected = 'guid:' + guid if guid else 'hwnd:' + str(int(handle)) + ':' + str(uid)
        backend = row.get('backend', 'CALLBACK')
        actions = row.get('actions', sorted(EVENTS) if row['callback'] else [])
        if not isinstance(backend, str) or backend not in {'CALLBACK', 'UIA', 'TOOLBAR', 'OVERFLOW', 'DISPLAY'}:
            raise ValueError('Invalid notification provider')
        if (not isinstance(actions, list) or any(not isinstance(action, str) for action in actions) or
                len(set(actions)) != len(actions) or any(action not in EVENTS for action in actions)):
            raise ValueError('Invalid notification actions')
        if backend in {'UIA', 'TOOLBAR'}:
            key = _text(row['key'], 68, empty=False)
            if not key.startswith('uia:') or len(key) != 68 or any(char not in '0123456789abcdef' for char in key[4:]):
                raise ValueError('Invalid notification UIA identity')
            expected = key
            if row['callback'] or row['version'] or row['guid'] or row['uid'] or row['window_class'] != 'Shell_TrayWnd':
                raise ValueError('UIA identity must not impersonate an application callback')
            if backend == 'TOOLBAR' and (not 10240 <= result.get('platform', 0) < 22000 or actions != sorted(EVENTS)):
                raise ValueError('Toolbar proxy is only valid for the original Windows10 control')
            if backend == 'TOOLBAR':
                _decimal(row.get('toolbar_handle'))
                _integer(row.get('toolbar_thread'), 1, 0xffffffff)
                if set(row) & {'overflow_handle', 'overflow_thread'}:
                    _decimal(row.get('overflow_handle'))
                    _integer(row.get('overflow_thread'), 1, 0xffffffff)
                rect = row.get('button_rect')
                if (not isinstance(rect, list) or len(rect) != 4 or
                        any(type(item) is not int or not -(1 << 31) <= item < 1 << 31 for item in rect) or
                        not 4 <= rect[2] - rect[0] <= 256 or not 4 <= rect[3] - rect[1] <= 256):
                    raise ValueError('Invalid original notification button geometry')
            if backend == 'UIA' and actions not in ([], ['LEFT']):
                raise ValueError('UIA only exposes an actual provider default action')
        elif backend == 'DISPLAY' and (row['callback'] or row['version'] or actions):
            raise ValueError('Metadata-only icons cannot expose guessed callbacks')
        elif backend == 'OVERFLOW' and (row['callback'] or row['version'] or not row['tip'] or
                not 10240 <= result.get('platform', 0) < 22000 or actions != ['LEFT', 'RIGHT', 'DOUBLE']):
            raise ValueError('On-demand original overflow requires real Windows10 metadata')
        if backend != 'TOOLBAR' and set(row) & TOOLBAR_FIELDS:
            raise ValueError('Native toolbar geometry is not valid for this provider')
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
    if not value.get('enabled') or not isinstance(event, str) or event not in EVENTS:
        raise ValueError('Notification area is unavailable')
    row = next((row for row in value['icons'] if row['key'] == key), None)
    _integer(x, -32768, 32767)
    _integer(y, -32768, 32767)
    if isinstance(key, str) and key.startswith('system:'):
        control = next((item for item in value.get('controls', []) if 'system:' + item['key'] == key), None)
        if control is None or event not in control['actions']:
            raise ValueError('Windows system notification control is unavailable')
        notification_system.request(control['key'], event, value.get('platform', 0))
        return {'command': 'system', 'key': control['key'], 'event': event}
    if row is None:
        raise ValueError('This notification icon changed or exited')
    actions = row.get('actions', EVENTS if row['callback'] else ())
    if event not in actions or (not row['callback'] and row.get('backend') not in {'UIA', 'TOOLBAR', 'OVERFLOW'}):
        raise ValueError('Historical icon cannot provide this action; use Original Windows Notification Area')
    return {'command': 'activate', 'key': row['key'], 'event': event, 'x': x, 'y': y}
