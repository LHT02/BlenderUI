# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only task enumeration; explicit buttons may activate/minimize a validated HWND."""
import ctypes as c
from ctypes import wintypes as w
import os


def _api():
    user = c.WinDLL('user32', use_last_error=True)
    for name, result, args in (
        ('IsWindow', w.BOOL, [w.HWND]), ('IsWindowVisible', w.BOOL, [w.HWND]),
        ('IsIconic', w.BOOL, [w.HWND]), ('GetWindow', w.HWND, [w.HWND, w.UINT]),
        ('GetWindowThreadProcessId', w.DWORD, [w.HWND, c.POINTER(w.DWORD)]),
        ('GetWindowTextW', c.c_int, [w.HWND, w.LPWSTR, c.c_int]),
        ('GetClassNameW', c.c_int, [w.HWND, w.LPWSTR, c.c_int]),
        ('GetWindowLongPtrW', c.c_ssize_t, [w.HWND, c.c_int]),
        ('ShowWindowAsync', w.BOOL, [w.HWND, c.c_int]),
        ('SetForegroundWindow', w.BOOL, [w.HWND]),
        ('GetForegroundWindow', w.HWND, []),
    ):
        fn = getattr(user, name)
        fn.restype, fn.argtypes = result, args
    return user


def _process_start(pid):
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4
    kernel.GetProcessTimes.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ''
    created, exited, system, user = (w.FILETIME() for _ in range(4))
    try:
        if not kernel.GetProcessTimes(handle, c.byref(created), c.byref(exited),
                                      c.byref(system), c.byref(user)):
            return ''
        return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def _identity(user, handle, starts=None):
    if not user.IsWindow(handle):
        return None
    pid, name = w.DWORD(), c.create_unicode_buffer(256)
    thread = user.GetWindowThreadProcessId(handle, c.byref(pid))
    if not thread or not pid.value or user.GetClassNameW(handle, name, len(name)) <= 0:
        return None
    if starts is not None:
        if pid.value not in starts:
            starts[pid.value] = _process_start(pid.value)
        started = starts[pid.value]
    else:
        started = _process_start(pid.value)
    return pid.value, int(thread), started, name.value


def tasks():
    if os.name != 'nt':
        return []
    user = _api()
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    result = []
    foreground = user.GetForegroundWindow()
    starts = {}
    def visit(handle, _parameter):
        if len(result) >= 256:
            return False
        if not user.IsWindowVisible(handle) or user.GetWindow(handle, 4):
            return True
        if user.GetWindowLongPtrW(handle, -20) & 0x80:  # tool window
            return True
        title = c.create_unicode_buffer(512)
        if user.GetWindowTextW(handle, title, len(title)) <= 0:
            return True
        identity = _identity(user, handle, starts)
        if identity is None:
            return True
        pid, thread, started, name = identity
        result.append({'handle': str(handle), 'pid': pid, 'title': title.value,
                       'thread_id': thread, 'process_started': started, 'window_class': name,
                       'actionable': bool(started),
                       'active': handle == foreground, 'minimized': bool(user.IsIconic(handle))})
        return True
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.EnumWindows.restype = w.BOOL
    user.EnumWindows(callback_type(visit), 0)
    return result


def act(handle, pid, minimize=False, *, identity=None):
    if (not isinstance(identity, (tuple, list)) or len(identity) != 3 or
        type(identity[0]) is not int or not 0 < identity[0] <= 0xffffffff or
        not isinstance(identity[1], str) or not identity[1].isdigit() or
        len(identity[1]) > 20 or int(identity[1]) <= 0 or
        not isinstance(identity[2], str) or not 0 < len(identity[2]) <= 255 or '\x00' in identity[2]):
        raise ValueError('This task has no verified identity; refresh the taskbar')
    if type(pid) is not int or not 0 < pid <= 0xffffffff or type(minimize) is not bool:
        raise ValueError('Invalid desktop task')
    if not isinstance(handle, (str, int)) or isinstance(handle, bool):
        raise ValueError('Invalid desktop window')
    if isinstance(handle, str) and (not handle.isdigit() or len(handle) > 20):
        raise ValueError('Invalid desktop window')
    handle = int(handle)
    if not 0 < handle < 1 << (c.sizeof(c.c_void_p) * 8):
        raise ValueError('Invalid desktop window')
    user = _api()
    expected = (pid, *identity)
    if _identity(user, handle) != expected:
        raise RuntimeError('This task changed; refresh the taskbar')
    # Recheck immediately before the asynchronous action, including PID reuse and window class.
    if _identity(user, handle) != expected:
        raise RuntimeError('This task changed; refresh the taskbar')
    user.ShowWindowAsync(handle, 6 if minimize else 9 if user.IsIconic(handle) else 5)
    return bool(minimize or user.SetForegroundWindow(handle))
