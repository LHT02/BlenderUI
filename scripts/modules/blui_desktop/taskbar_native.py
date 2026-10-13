# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows taskbar identities and guarded visibility actions (helper process only)."""
import ctypes as c
from ctypes import wintypes as w
import os
from . import native_windows

CLASSES = frozenset(('Shell_TrayWnd', 'Shell_SecondaryTrayWnd'))


def validate_record(row):
    if not isinstance(row, dict) or set(row) != {
            'handle', 'pid', 'thread_id', 'process_started', 'window_class', 'visible'}:
        raise ValueError('Invalid Windows taskbar recovery record')
    if (not isinstance(row['handle'], str) or not row['handle'].isdigit() or
            not 0 < int(row['handle']) < 1 << (c.sizeof(c.c_void_p) * 8) or
            len(row['handle']) > 20 or
            any(type(row[key]) is not int or not 0 < row[key] <= 0xffffffff
                for key in ('pid', 'thread_id')) or
            not isinstance(row['process_started'], str) or
            not row['process_started'].isdigit() or len(row['process_started']) > 20 or
            not 0 < int(row['process_started']) < 1 << 64 or
            not isinstance(row['window_class'], str) or
            row['window_class'] not in CLASSES or row['visible'] is not True):
        raise ValueError('Invalid Windows taskbar recovery identity')
    return row


def identity_key(row):
    return tuple(row[key] for key in ('handle', 'pid', 'thread_id',
                                     'process_started', 'window_class'))


class WindowsBars:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Windows taskbar control is only available on Windows')
        self.user = native_windows._api()
        self.user.GetShellWindow.argtypes, self.user.GetShellWindow.restype = [], w.HWND
        self.user.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
        self.user.SetWindowPos.restype = w.BOOL
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR,
                                                        c.POINTER(w.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = w.BOOL
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [w.HANDLE], w.BOOL

    def _explorer(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            name, length = c.create_unicode_buffer(32768), w.DWORD(32768)
            return bool(self.kernel.QueryFullProcessImageNameW(handle, 0, name, c.byref(length))
                        and os.path.basename(name.value).casefold() == 'explorer.exe')
        finally:
            self.kernel.CloseHandle(handle)

    def current(self, handle):
        identity = native_windows._identity(self.user, int(handle))
        if identity is None:
            return None
        pid, thread, started, name = identity
        shell_pid = w.DWORD()
        shell = self.user.GetShellWindow()
        if (name not in CLASSES or not started or not shell or
                not self.user.GetWindowThreadProcessId(shell, c.byref(shell_pid)) or
                shell_pid.value != pid or not self._explorer(pid)):
            return None
        return {'handle': str(int(handle)), 'pid': pid, 'thread_id': thread,
                'process_started': started, 'window_class': name,
                'visible': bool(self.user.IsWindowVisible(int(handle)))}

    def enumerate(self):
        rows = []
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def visit(handle, _):
            if len(rows) >= 32:
                return False
            name = c.create_unicode_buffer(256)
            self.user.GetClassNameW(handle, name, len(name))
            if name.value in CLASSES:
                row = self.current(handle)
                if row is not None:
                    rows.append(row)
            return True
        self.user.EnumWindows.argtypes = [callback_type, w.LPARAM]
        self.user.EnumWindows.restype = w.BOOL
        self.user.EnumWindows(callback_type(visit), 0)
        return rows

    def matches(self, row):
        current = self.current(row['handle'])
        return current is not None and identity_key(current) == identity_key(row)

    def set_visible(self, row, visible):
        validate_record(row)
        if not self.matches(row) or not self.matches(row):
            return False
        # Visibility-only, asynchronous and non-activating; do not move, resize,
        # restack or alter the user's persistent automatic-hide/AppBar state.
        flags = 0x4000 | 0x1 | 0x2 | 0x4 | 0x10 | 0x200 | (0x40 if visible else 0x80)
        return bool(self.user.SetWindowPos(int(row['handle']), None, 0, 0, 0, 0, flags))

    def visible(self, row):
        return bool(self.matches(row) and self.user.IsWindowVisible(int(row['handle'])))


class OwnerProcess:
    """Retains one kernel handle, not a reusable PID, for the entire guard lifetime."""
    def __init__(self, pid, started):
        if (type(pid) is not int or not 0 < pid <= 0xffffffff or
                not isinstance(started, str) or not started.isdigit()):
            raise ValueError('Invalid taskbar owner process')
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        self.kernel.WaitForSingleObject.restype = w.DWORD
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        self.handle = self.kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        if not self.handle or native_windows._process_start(pid) != started:
            self.close()
            raise RuntimeError('The BLUI taskbar owner changed or exited')

    def alive(self):
        return bool(self.handle and self.kernel.WaitForSingleObject(self.handle, 0) == 0x102)

    def close(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class SessionLock:
    def __init__(self):
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]
        self.kernel.CreateMutexW.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        c.set_last_error(0)
        self.handle = self.kernel.CreateMutexW(None, False, 'Local\\BLUI.TaskbarGuard.v1')
        if not self.handle or c.get_last_error() == 183:
            self.close()
            raise RuntimeError('Another BLUI taskbar guard is already running')

    def close(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None
