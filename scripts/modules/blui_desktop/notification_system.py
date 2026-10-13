# SPDX-License-Identifier: GPL-2.0-or-later
"""Fixed Windows system-notification controls, independent from app HWND callbacks.

Win11 fallback actions follow Windows shortcuts / ms-settings URIs; the network
flyout URI is version-dependent and explicitly falls back to network settings. ManagedShell
is an Apache-2.0 design reference; no implementation is copied or linked.
"""
import sys

LABELS = {'NETWORK': ('Network', 'NETWORK_DRIVE'), 'VOLUME': ('Volume', 'SOUND'),
          'POWER': ('Power and Battery', 'LIGHT_SUN'), 'INPUT': ('Input Language', 'FONT_DATA'),
          'NOTIFICATIONS': ('Notifications', 'INFO'), 'CALENDAR': ('Calendar', 'TIME'),
          'ORIGINAL_TRAY': ('Original Windows Notification Area', 'WINDOW')}
GUID_ACTIONS = {'7820ae74-23e3-4229-82c1-e41cb67d5b9c': 'NETWORK',
                '7820ae73-23e3-4229-82c1-e41cb67d5b9c': 'VOLUME',
                '7820ae75-23e3-4229-82c1-e41cb67d5b9c': 'POWER'}
SETTINGS = {'NETWORK': 'ms-settings:network-status', 'VOLUME': 'ms-settings:sound',
            'POWER': 'ms-settings:powersleep', 'INPUT': 'ms-settings:typing',
            'NOTIFICATIONS': 'ms-settings:notifications', 'CALENDAR': 'ms-settings:dateandtime',
            'ORIGINAL_TRAY': 'ms-settings:taskbar'}


def build_number():
    return sys.getwindowsversion().build if sys.platform == 'win32' else 0


def controls(build, *, private=False):
    if type(build) is not int or build < 0:
        raise ValueError('Invalid Windows platform version')
    if private or build < 10240:
        return []
    return [{'key': key, 'label': label, 'icon': icon, 'actions': ['LEFT', 'RIGHT', 'DOUBLE'],
             'status': ''} for key, (label, icon) in LABELS.items()]


def request(key, event, build):
    """No strings from tooltip/search/app metadata ever become an executable or URI."""
    if (not isinstance(key, str) or not isinstance(event, str) or key not in LABELS or
            event not in {'LEFT', 'RIGHT', 'DOUBLE'} or type(build) is not int or build < 10240):
        raise ValueError('Unsupported Windows system notification action')
    if event in {'RIGHT', 'DOUBLE'}:
        return {'kind': 'URI', 'value': SETTINGS[key]}
    if key == 'NETWORK':
        return {'kind': 'URI', 'value': 'ms-availablenetworks:'}
    if key == 'VOLUME':
        return {'kind': 'KEYS', 'value': ['WIN', 'A']} if build >= 22000 else {'kind': 'SOUND_VOLUME'}
    if key == 'POWER':
        return {'kind': 'URI', 'value': SETTINGS[key]}
    if key == 'INPUT':
        return {'kind': 'KEYS', 'value': ['WIN', 'SPACE']}
    if key == 'NOTIFICATIONS':
        return {'kind': 'KEYS', 'value': ['WIN', 'N' if build >= 22000 else 'A']}
    if key == 'CALENDAR':
        return {'kind': 'KEYS', 'value': ['WIN', 'N']} if build >= 22000 else {'kind': 'KEYS', 'value': ['WIN', 'ALT', 'D']}
    return {'kind': 'KEYS', 'value': ['WIN', 'B']}


def validate_controls(rows):
    if not isinstance(rows, list) or len(rows) > len(LABELS):
        raise ValueError('Invalid system notification controls')
    result, used = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'key', 'label', 'icon', 'actions', 'status'}:
            raise ValueError('Invalid system notification control')
        key = row['key']
        if not isinstance(key, str) or key not in LABELS or key in used or (row['label'], row['icon']) != LABELS[key]:
            raise ValueError('Invalid system notification control identity')
        if row['actions'] != ['LEFT', 'RIGHT', 'DOUBLE'] or not isinstance(row['status'], str) or len(row['status']) > 127 or '\0' in row['status']:
            raise ValueError('Invalid system notification control state')
        used.add(key)
        result.append(dict(row, actions=list(row['actions'])))
    return result
