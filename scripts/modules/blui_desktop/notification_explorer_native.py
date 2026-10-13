# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only discovery of Win10's existing Explorer-owned overflow provider."""
import ctypes as c
from ctypes import wintypes as w
import time
from . import native_windows, notification_system
from . import notification_uia_native as uia


def overflow_windows(source, identity):
    if not 10240 <= notification_system.build_number() < 22000:
        return []
    root, owner = source
    if owner[3] != 'Shell_TrayWnd' or identity(root) != owner:
        return []
    user, rows = native_windows._api(), []
    prototype = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def visit(handle, _parameter):
        item = identity(handle)
        if (item and item[3] == 'NotifyIconOverflowWindow' and item[0] == owner[0] and item[2] == owner[2] and
                identity(handle) == item and identity(root) == owner):
            rows.append((int(handle), item))
        return len(rows) < 2
    user.EnumWindows.argtypes, user.EnumWindows.restype = [prototype, w.LPARAM], w.BOOL
    user.EnumWindows(prototype(visit), 0)
    return rows if identity(root) == owner else []


def _chevron(source, session, identity):
    root, owner = source
    if not 10240 <= notification_system.build_number() < 22000 or identity(root) != owner or owner[3] != 'Shell_TrayWnd':
        raise ValueError('Original Win10 notification provider is unavailable')
    user = native_windows._api()
    user.FindWindowExW.argtypes, user.FindWindowExW.restype = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR], w.HWND
    user.GetDlgItem.argtypes, user.GetDlgItem.restype = [w.HWND, c.c_int], w.HWND
    user.GetParent.argtypes, user.GetParent.restype = [w.HWND], w.HWND
    user.GetDlgCtrlID.argtypes, user.GetDlgCtrlID.restype = [w.HWND], c.c_int
    notify = user.FindWindowExW(root, None, 'TrayNotifyWnd', None)
    tray_owner = identity(notify) if notify else None
    button = user.GetDlgItem(notify, 1502) if tray_owner else None
    button_owner = identity(button) if button else None
    if (not tray_owner or tray_owner[0] != owner[0] or tray_owner[2] != owner[2] or tray_owner[3] != 'TrayNotifyWnd' or
            not button_owner or button_owner[0] != owner[0] or button_owner[2] != owner[2] or button_owner[3] != 'Button' or
            user.GetParent(button) != notify or user.GetDlgCtrlID(button) != 1502):
        raise ValueError('Original Win10 tray expansion control is not supported')
    element = session.element(button)
    try:
        item = session.describe(element)
        if (item['handle'] != button or item['pid'] != owner[0] or item['class'] != 'Button' or item['id'] != '1502' or
                item['type'] != 50000 or not item['enabled']):
            raise ValueError('Original Win10 tray expansion element changed')
        return user, int(notify), tray_owner, int(button), button_owner, element, item['runtime']
    except Exception:
        uia.release(element)
        raise


def _invoke(source, session, identity, target):
    user, notify, tray_owner, button, button_owner, element, runtime = target
    if (identity(source[0]) != source[1] or identity(notify) != tray_owner or identity(button) != button_owner or
            user.GetParent(button) != notify or user.GetDlgCtrlID(button) != 1502 or session.runtime_id(element) != runtime):
        raise ValueError('Original tray expansion control changed before invocation')
    pattern, slot = session.action_pattern(element)
    try:
        if not pattern:
            raise ValueError('Original tray expansion control has no real default action')
        uia.checked(uia.call(pattern, slot, uia.HRESULT, []))
    finally:
        uia.release(pattern)


def _last_input(user):
    class Info(c.Structure):
        _fields_ = [('size', w.UINT), ('tick', w.DWORD)]
    user.GetLastInputInfo.argtypes, user.GetLastInputInfo.restype = [c.POINTER(Info)], w.BOOL
    value = Info(c.sizeof(Info), 0)
    return value.tick if user.GetLastInputInfo(c.byref(value)) else None


def open_overflow(source, session, identity):
    """Only explicit item clicks call this; no automatic taskbar visibility changes."""
    user = native_windows._api()
    current = [row for row in overflow_windows(source, identity) if user.IsWindowVisible(row[0])]
    if len(current) == 1:
        return {'container': current[0], 'target': None, 'input': None, 'foreground': 0, 'foreground_owner': None}
    if current:
        raise ValueError('Ambiguous original Windows notification overflow')
    target = _chevron(source, session, identity)
    try:
        stamp = _last_input(target[0])
        _invoke(source, session, identity, target)
        end = time.monotonic() + 1.25
        while time.monotonic() < end:
            current = [row for row in overflow_windows(source, identity) if user.IsWindowVisible(row[0])]
            if len(current) == 1:
                foreground = user.GetForegroundWindow()
                return {'container': current[0], 'target': target, 'input': stamp,
                        'foreground': int(foreground or 0), 'foreground_owner': identity(foreground) if foreground else None}
            if identity(source[0]) != source[1]:
                break
            time.sleep(.02)  # Isolated helper thread, never Blender or its message pump.
        raise ValueError('Original Windows notification overflow did not open')
    except Exception:
        uia.release(target[5])
        raise


def close_overflow(source, session, identity, state):
    """Restore only the exact dropdown opened here, unless real user input changed."""
    target = state.get('target')
    if not target:
        return
    try:
        container, expected = state['container']
        user = target[0]
        # RIGHT/DOUBLE may open an app-owned context menu/window. Never toggle
        # Explorer's control under that popup; normal Windows focus closes it.
        foreground = state.get('foreground', 0)
        if (state.get('action') not in {'RIGHT', 'DOUBLE'} and
                state['input'] is not None and _last_input(user) == state['input'] and
                user.GetForegroundWindow() == foreground and
                (not foreground or state.get('foreground_owner') is not None and identity(foreground) == state['foreground_owner']) and
                identity(source[0]) == source[1] and identity(container) == expected and user.IsWindowVisible(container)):
            _invoke(source, session, identity, target)
    finally:
        uia.release(target[5])
