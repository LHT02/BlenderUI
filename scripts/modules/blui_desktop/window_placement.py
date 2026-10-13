# SPDX-License-Identifier: GPL-2.0-or-later
"""Place only explicit, live BLUI native HWNDs in physical-pixel work areas.

No window enumeration, foreign-window lookup, DPI-awareness changes or display
configuration writes are performed. Call with Window.blui_native_handle from a
fresh, live bpy Window, not a handle retained across close/load/undo boundaries.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from . import monitors, native_windows


def _handle(value):
    if (not isinstance(value, (str, int)) or isinstance(value, bool) or
            (isinstance(value, str) and (not value.isdigit() or len(value) > 20))):
        raise ValueError('Invalid BLUI native window handle')
    value = int(value)
    if not 0 < value < 1 << (c.sizeof(c.c_void_p) * 8):
        raise ValueError('Invalid BLUI native window handle')
    return value


def _api():
    if os.name != 'nt':
        raise RuntimeError('Native window placement is only available on Windows')
    user = native_windows._api()
    user.GetWindowRect.argtypes, user.GetWindowRect.restype = [w.HWND, c.POINTER(w.RECT)], w.BOOL
    user.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
    user.SetWindowPos.restype = w.BOOL
    try:
        user.GetDpiForWindow.argtypes, user.GetDpiForWindow.restype = [w.HWND], w.UINT
    except AttributeError:
        pass
    return user


def _own(user, handle):
    value = native_windows._identity(user, handle)
    if (value is None or value[0] != os.getpid() or not value[2] or
            value[3] != 'GHOST_WindowClass'):
        raise RuntimeError('This native window is not a live BLUI-owned window')
    return value


def bounds(handle):
    """Return the outer SetWindowPos rectangle, visual frame and effective window DPI."""
    handle, user = _handle(handle), _api()
    identity = _own(user, handle)
    rect = w.RECT()
    if not user.GetWindowRect(handle, c.byref(rect)):
        raise OSError('Unable to read the BLUI window rectangle')
    outer = [rect.left, rect.top, rect.right, rect.bottom]
    monitors._rect(outer)
    frame = list(outer)
    try:
        dwm = c.WinDLL('dwmapi', use_last_error=True)
        dwm.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, c.c_void_p, w.DWORD]
        dwm.DwmGetWindowAttribute.restype = c.c_long
        if dwm.DwmGetWindowAttribute(handle, 9, c.byref(rect), c.sizeof(rect)) == 0:
            candidate = [rect.left, rect.top, rect.right, rect.bottom]
            monitors._rect(candidate)
            frame = candidate
    except (OSError, AttributeError, ValueError):
        pass
    dpi = 96
    try:
        dpi = int(user.GetDpiForWindow(handle)) or 96
    except AttributeError:
        pass
    if _own(user, handle) != identity:
        raise RuntimeError('The BLUI window changed during placement')
    return {'rect': outer, 'frame': frame, 'dpi': [dpi, dpi]}


def place(handle, rect, displays, *, preferred=''):
    """Schedule a non-activating move; never restore/minimize/maximize another window."""
    handle = _handle(handle)
    rect = monitors._rect(rect)
    rows = monitors.validate(displays)['monitors']
    candidates = [row for row in rows if not preferred or row['device'] == preferred]
    if not any(row['work'][0] <= rect[0] < rect[2] <= row['work'][2] and
               row['work'][1] <= rect[1] < rect[3] <= row['work'][3] for row in candidates):
        raise ValueError('The BLUI window must remain inside a connected monitor work area')
    user = _api()
    identity = _own(user, handle)
    if _own(user, handle) != identity:
        raise RuntimeError('The BLUI window changed before placement')
    # ASYNCWINDOWPOS | NOACTIVATE | NOZORDER | NOOWNERZORDER: no focus stealing.
    if not user.SetWindowPos(handle, None, rect[0], rect[1], rect[2] - rect[0],
                             rect[3] - rect[1], 0x4000 | 0x10 | 0x4 | 0x200):
        raise OSError('Unable to move the BLUI desktop window')
    return True


def recover(handle, displays, *, preferred=''):
    """Move back only completely off-screen BLUI windows, preserving partly visible ones."""
    current = bounds(handle)
    rect = current['rect']
    rows = monitors.validate(displays)['monitors']
    if not rows or any(rect[0] < row['work'][2] and rect[2] > row['work'][0] and
                       rect[1] < row['work'][3] and rect[3] > row['work'][1] for row in rows):
        return False
    suggestion = monitors.placement(rect, displays, preferred=preferred, old_dpi=current['dpi'])
    return place(handle, suggestion['rect'], displays, preferred=suggestion['device'])
