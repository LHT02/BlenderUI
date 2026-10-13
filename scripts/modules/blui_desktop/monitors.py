# SPDX-License-Identifier: GPL-2.0-or-later
"""Worker-only display enumeration and pure, read-only placement suggestions.

No SetWindowPos, display-mode change, Explorer mutation, or foreign-window
enumeration is performed here. The native owner must recheck window identity
and only apply suggestions to its own live BLUI windows.
"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os

MAX_MONITORS = 32


class _MonitorInfo(c.Structure):
    _fields_ = [('size', w.DWORD), ('monitor', w.RECT), ('work', w.RECT),
                ('flags', w.DWORD), ('device', w.WCHAR * 32)]


def _rect(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4 or not all(
            type(item) is int and abs(item) <= 1000000 for item in value):
        raise ValueError('Invalid desktop monitor rectangle')
    if value[2] <= value[0] or value[3] <= value[1]:
        raise ValueError('Invalid desktop monitor dimensions')
    return list(value)


def validate(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('coordinate_space') != 'physical':
        raise ValueError('Invalid desktop monitor snapshot')
    rows = snapshot.get('monitors')
    if not isinstance(rows, list) or len(rows) > MAX_MONITORS:
        raise ValueError('Invalid desktop monitor count')
    clean, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid desktop monitor')
        device = row.get('device')
        if (not isinstance(device, str) or not 0 < len(device) <= 255 or '\x00' in device or
                device in seen or type(row.get('primary')) is not bool):
            raise ValueError('Invalid desktop monitor identity')
        seen.add(device)
        monitor, work = _rect(row.get('rect')), _rect(row.get('work'))
        if not (monitor[0] <= work[0] < work[2] <= monitor[2] and
                monitor[1] <= work[1] < work[3] <= monitor[3]):
            raise ValueError('Invalid desktop monitor work area')
        dpi = row.get('dpi')
        if not isinstance(dpi, (list, tuple)) or len(dpi) != 2 or not all(
                type(item) is int and 48 <= item <= 960 for item in dpi):
            raise ValueError('Invalid desktop monitor DPI')
        clean.append({'device': device, 'rect': monitor, 'work': work,
                      'dpi': list(dpi), 'primary': row['primary']})
    clean.sort(key=lambda row: row['device'])
    return {'coordinate_space': 'physical', 'monitors': clean}


def topology_key(snapshot):
    return hashlib.sha256(json.dumps(validate(snapshot), sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def snapshot():
    """Call only from a dedicated service process, never a draw callback or UI timer."""
    if os.name != 'nt':
        return {'coordinate_space': 'physical', 'monitors': []}
    user = c.WinDLL('user32', use_last_error=True)
    try:
        shcore = c.WinDLL('shcore', use_last_error=True)
        shcore.SetProcessDpiAwareness.argtypes = [c.c_int]
        shcore.SetProcessDpiAwareness.restype = c.c_long
        shcore.SetProcessDpiAwareness(2)  # Only this disposable worker process.
        shcore.GetDpiForMonitor.argtypes = [w.HANDLE, c.c_int, c.POINTER(w.UINT), c.POINTER(w.UINT)]
        shcore.GetDpiForMonitor.restype = c.c_long
    except (OSError, AttributeError):
        shcore = None
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HANDLE, w.HDC, c.POINTER(w.RECT), w.LPARAM)
    user.GetMonitorInfoW.argtypes = [w.HANDLE, c.POINTER(_MonitorInfo)]
    user.GetMonitorInfoW.restype = w.BOOL
    user.EnumDisplayMonitors.argtypes = [w.HDC, c.POINTER(w.RECT), callback_type, w.LPARAM]
    user.EnumDisplayMonitors.restype = w.BOOL
    rows, failures = [], []

    def visit(handle, _dc, _rect_pointer, _parameter):
        if len(rows) >= MAX_MONITORS:
            return False
        try:
            info = _MonitorInfo()
            info.size = c.sizeof(info)
            if not user.GetMonitorInfoW(handle, c.byref(info)):
                raise OSError('Desktop monitor changed during enumeration')
            dpi_x, dpi_y = w.UINT(96), w.UINT(96)
            if shcore and shcore.GetDpiForMonitor(handle, 0, c.byref(dpi_x), c.byref(dpi_y)) != 0:
                dpi_x.value = dpi_y.value = 96
            rows.append({'device': info.device,
                         'rect': [info.monitor.left, info.monitor.top, info.monitor.right, info.monitor.bottom],
                         'work': [info.work.left, info.work.top, info.work.right, info.work.bottom],
                         'dpi': [dpi_x.value, dpi_y.value], 'primary': bool(info.flags & 1)})
        except (OSError, ValueError) as exc:
            failures.append(str(exc))
            return False
        return True

    result = user.EnumDisplayMonitors(None, None, callback_type(visit), 0)
    if failures or (not result and len(rows) < MAX_MONITORS):
        raise OSError(failures[0] if failures else 'Desktop monitor enumeration failed')
    return validate({'coordinate_space': 'physical', 'monitors': rows})


def placement(rect, displays, *, preferred='', old_dpi=None):
    """Recommend a fully visible window rectangle, including negative-origin monitors.

    Coordinates are Win32 physical screen pixels (top-left origin). Existing
    rectangles already inside any work area are unchanged. A removed display
    falls back to the closest surviving work area; canvas node positions are
    deliberately unaffected by monitor geometry or DPI changes.
    """
    rect = _rect(rect)
    rows = validate(displays)['monitors']
    if not rows:
        return None
    for row in rows:
        left, top, right, bottom = row['work']
        if left <= rect[0] < rect[2] <= right and top <= rect[1] < rect[3] <= bottom:
            return {'rect': rect, 'device': row['device'], 'dpi': row['dpi'], 'changed': False}
    center = ((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)

    def distance(row):
        left, top, right, bottom = row['work']
        x, y = min(max(center[0], left), right), min(max(center[1], top), bottom)
        return (x - center[0]) ** 2 + (y - center[1]) ** 2, not row['primary']

    target = next((row for row in rows if row['device'] == preferred), None) or min(rows, key=distance)
    left, top, right, bottom = target['work']
    scale_x = scale_y = 1.0
    if old_dpi is not None:
        if not isinstance(old_dpi, (list, tuple)) or len(old_dpi) != 2 or not all(
                type(item) is int and 48 <= item <= 960 for item in old_dpi):
            raise ValueError('Invalid previous desktop DPI')
        scale_x, scale_y = target['dpi'][0] / old_dpi[0], target['dpi'][1] / old_dpi[1]
    width = min(right - left, max(min(200, right - left), round((rect[2] - rect[0]) * scale_x)))
    height = min(bottom - top, max(min(120, bottom - top), round((rect[3] - rect[1]) * scale_y)))
    x = min(max(rect[0], left), right - width)
    y = min(max(rect[1], top), bottom - height)
    recommended = [x, y, x + width, y + height]
    return {'rect': recommended, 'device': target['device'], 'dpi': target['dpi'],
            'changed': recommended != rect}
