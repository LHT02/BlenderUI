# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only task enumeration; explicit buttons may activate/minimize a validated HWND."""
import ctypes as c
from ctypes import wintypes as w
import os
import subprocess
from . import taskbar_groups


class _MonitorInfo(c.Structure):
    _fields_ = [('size', w.DWORD), ('monitor', w.RECT), ('work', w.RECT),
                ('flags', w.DWORD), ('device', w.WCHAR * 32)]


def _metadata(pid):
    """Kernel process identity, not extension-controlled Shell display strings."""
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = w.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    value = {'executable': '', 'app_id': ''}
    if not handle:
        return value
    try:
        path, length = c.create_unicode_buffer(32768), w.DWORD(32768)
        if kernel.QueryFullProcessImageNameW(handle, 0, path, c.byref(length)):
            value['executable'] = path.value
        try:
            function = kernel.GetApplicationUserModelId
            function.argtypes, function.restype = [w.HANDLE, c.POINTER(w.UINT), w.LPWSTR], w.LONG
            count = w.UINT()
            if function(handle, c.byref(count), None) == 122 and 0 < count.value <= 513:
                app_id = c.create_unicode_buffer(count.value)
                if function(handle, c.byref(count), app_id) == 0:
                    value['app_id'] = app_id.value
        except AttributeError:
            pass
        return value
    finally:
        kernel.CloseHandle(handle)


def _monitor(user, handle):
    user.MonitorFromWindow.argtypes, user.MonitorFromWindow.restype = [w.HWND, w.DWORD], w.HANDLE
    user.GetMonitorInfoW.argtypes, user.GetMonitorInfoW.restype = [w.HANDLE, c.POINTER(_MonitorInfo)], w.BOOL
    monitor = user.MonitorFromWindow(handle, 2)
    info = _MonitorInfo()
    info.size = c.sizeof(info)
    return info.device if monitor and user.GetMonitorInfoW(monitor, c.byref(info)) else ''


def _cloaked(handle):
    try:
        dwm = c.WinDLL('dwmapi', use_last_error=True)
        dwm.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, c.c_void_p, w.DWORD]
        dwm.DwmGetWindowAttribute.restype = w.LONG
        value = w.DWORD()
        return dwm.DwmGetWindowAttribute(handle, 14, c.byref(value), c.sizeof(value)) == 0 and bool(value.value)
    except (OSError, AttributeError):
        return False


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
    starts, metadata = {}, {}
    def visit(handle, _parameter):
        if len(result) >= 256:
            return False
        extended = user.GetWindowLongPtrW(handle, -20)
        if (not user.IsWindowVisible(handle) or
                (user.GetWindow(handle, 4) and not extended & 0x40000) or _cloaked(handle)):
            return True
        if extended & 0x80:  # tool window
            return True
        title = c.create_unicode_buffer(512)
        if user.GetWindowTextW(handle, title, len(title)) <= 0:
            return True
        identity = _identity(user, handle, starts)
        if identity is None:
            return True
        pid, thread, started, name = identity
        if pid not in metadata:
            metadata[pid] = _metadata(pid) if started else {'executable': '', 'app_id': ''}
        # Identity metadata is untrusted if the process/window changed mid-snapshot.
        if _identity(user, handle) != identity:
            return True
        row = {'handle': str(handle), 'pid': pid, 'title': title.value,
                       'thread_id': thread, 'process_started': started, 'window_class': name,
                       'actionable': bool(started),
               'active': handle == foreground, 'minimized': bool(user.IsIconic(handle)),
               **metadata[pid], 'monitor': _monitor(user, handle)}
        row['group_key'] = taskbar_groups.identity_key(row)
        result.append(row)
        return True
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.EnumWindows.restype = w.BOOL
    user.EnumWindows(callback_type(visit), 0)
    return result


def act(handle, pid, minimize=False, *, identity=None, toggle=False):
    if (not isinstance(identity, (tuple, list)) or len(identity) != 3 or
        type(identity[0]) is not int or not 0 < identity[0] <= 0xffffffff or
        not isinstance(identity[1], str) or not identity[1].isdigit() or
        len(identity[1]) > 20 or int(identity[1]) <= 0 or
        not isinstance(identity[2], str) or not 0 < len(identity[2]) <= 255 or '\x00' in identity[2]):
        raise ValueError('This task has no verified identity; refresh the taskbar')
    if (type(pid) is not int or not 0 < pid <= 0xffffffff or
            type(minimize) is not bool or type(toggle) is not bool):
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
    if toggle:
        # A user can activate a window between two background snapshots. The
        # no-activate taskbar leaves actual foreground unchanged on the click.
        minimize = user.GetForegroundWindow() == handle and not user.IsIconic(handle)
    # Recheck immediately before the asynchronous action, including PID reuse and window class.
    if _identity(user, handle) != expected:
        raise RuntimeError('This task changed; refresh the taskbar')
    user.ShowWindowAsync(handle, 6 if minimize else 9 if user.IsIconic(handle) else 5)
    return bool(minimize or user.SetForegroundWindow(handle))


def launch(row):
    """Explicit new instance, no shell/command string and no parameters from window titles."""
    if not isinstance(row, dict) or not taskbar_groups.can_launch(row):
        raise ValueError('This application cannot safely start a new instance')
    handle, pid = row.get('handle'), row.get('pid')
    identity = (row.get('thread_id'), row.get('process_started'), row.get('window_class'))
    # Reuse the exact strict validation contract without activating the application.
    if (not isinstance(handle, str) or not handle.isdigit() or len(handle) > 20 or
            type(pid) is not int or not 0 < pid <= 0xffffffff or
            type(identity[0]) is not int or not 0 < identity[0] <= 0xffffffff or
            not isinstance(identity[1], str) or not identity[1].isdigit() or len(identity[1]) > 20 or
            not isinstance(identity[2], str) or not 0 < len(identity[2]) <= 255 or '\x00' in identity[2]):
        raise ValueError('Invalid application launch identity')
    handle = int(handle)
    if not 0 < handle < 1 << (c.sizeof(c.c_void_p) * 8):
        raise ValueError('Invalid application launch window')
    user = _api()
    expected = (pid, *identity)
    if _identity(user, handle) != expected or user.GetWindowLongPtrW(handle, -20) & 0x80:
        raise RuntimeError('This application changed; refresh the taskbar')
    actual = _metadata(pid)
    if (not taskbar_groups.executable_path(actual['executable']) or
            taskbar_groups.identity_key({**row, **actual}) != taskbar_groups.identity_key(row) or
            actual['app_id'] or os.path.normcase(actual['executable']) != os.path.normcase(row['executable'])):
        raise RuntimeError('The application executable changed; refresh the taskbar')
    if _identity(user, handle) != expected:
        raise RuntimeError('This application changed; refresh the taskbar')
    # A program may elect to focus an existing instance. BLUI never bypasses its
    # single-instance policy or launches through cmd/PowerShell/Shell extensions.
    subprocess.Popen([actual['executable']], close_fds=True)
    return True
