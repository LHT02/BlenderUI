# SPDX-License-Identifier: GPL-2.0-or-later
"""Helper-only, verified Windows desktop parenting. No shell injection or registry writes.

Independent implementation; architecture reference: Lively's DesktopUtil and
WinDesktopCore core-separation branch. Interactive canvases are *above* DefView,
not wallpaper windows below it; input stays native to the BLUI HWND.
"""
import ctypes as c
from ctypes import wintypes as w
import os

from . import desktop_host_state as state, monitors, native_windows
from .taskbar_native import OwnerProcess

MARKER = 'BLUI.DesktopHost.v1'
INSTANCE = 'BLUI.DesktopInstance.v1'
WS_CHILD, WS_POPUP = 0x40000000, 0x80000000
WS_EX_LAYERED, WS_EX_NOREDIRECTIONBITMAP = 0x80000, 0x200000


class SessionLock:
    def __init__(self):
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]
        self.kernel.CreateMutexW.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        c.set_last_error(0)
        self.handle = self.kernel.CreateMutexW(None, False, 'Local\\BLUI.DesktopHost.v1')
        if not self.handle or c.get_last_error() == 183:
            self.close()
            raise RuntimeError('Another BLUI desktop host is already running')

    def close(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class SessionWitness:
    """Keep the session lock object alive until independent recovery has finished."""
    def __init__(self):
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenMutexW.argtypes, self.kernel.OpenMutexW.restype = [w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        self.handle = self.kernel.OpenMutexW(0x100000, False, 'Local\\BLUI.DesktopHost.v1')
        if not self.handle:
            raise RuntimeError('The desktop ownership lock disappeared')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class AbortEvent:
    """Per-generation emergency stop: a stale recovery guardian cannot abort a new host."""
    def __init__(self, nonce):
        if len(nonce) != 32 or any(char not in '0123456789abcdef' for char in nonce):
            raise ValueError('Invalid desktop host generation')
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        for name, result, args in (
            ('CreateEventW', w.HANDLE, [c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]),
            ('SetEvent', w.BOOL, [w.HANDLE]),
            ('WaitForSingleObject', w.DWORD, [w.HANDLE, w.DWORD]),
            ('CloseHandle', w.BOOL, [w.HANDLE]),
        ):
            function = getattr(self.kernel, name)
            function.restype, function.argtypes = result, args
        self.handle = self.kernel.CreateEventW(None, True, False, 'Local\\BLUI.DesktopAbort.' + nonce)
        if not self.handle:
            raise OSError('Unable to create desktop restoration signal')

    def aborted(self):
        return not self.handle or self.kernel.WaitForSingleObject(self.handle, 0) != 0x102

    def set(self):
        if self.handle:
            self.kernel.SetEvent(self.handle)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class DesktopWindows:
    def __init__(self, owner_pid=None, owner_started=None, abort=None):
        if os.name != 'nt':
            raise RuntimeError('Desktop replacement is available only on Windows')
        self.owner_pid, self.owner_started, self.abort = owner_pid, owner_started, abort
        self.restore_error = ''
        self.user = native_windows._api()
        signatures = (
            ('GetShellWindow', w.HWND, []),
            ('GetDesktopWindow', w.HWND, []),
            ('GetParent', w.HWND, [w.HWND]),
            ('FindWindowExW', w.HWND, [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]),
            ('GetWindowRect', w.BOOL, [w.HWND, c.POINTER(w.RECT)]),
            ('GetClientRect', w.BOOL, [w.HWND, c.POINTER(w.RECT)]),
            ('MapWindowPoints', c.c_int, [w.HWND, w.HWND, c.POINTER(w.POINT), w.UINT]),
            ('SetWindowLongPtrW', c.c_ssize_t, [w.HWND, c.c_int, c.c_ssize_t]),
            ('SetParent', w.HWND, [w.HWND, w.HWND]),
            ('GetPropW', w.HANDLE, [w.HWND, w.LPCWSTR]),
            ('SetWindowPos', w.BOOL, [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]),
            ('SetLayeredWindowAttributes', w.BOOL, [w.HWND, w.DWORD, w.BYTE, w.DWORD]),
            ('GetWindowDpiAwarenessContext', c.c_void_p, [w.HWND]),
            ('AreDpiAwarenessContextsEqual', w.BOOL, [c.c_void_p, c.c_void_p]),
            ('SetThreadDpiAwarenessContext', c.c_void_p, [c.c_void_p]),
        )
        for name, result, args in signatures:
            function = getattr(self.user, name)
            function.restype, function.argtypes = result, args
        # Changes only the disposable helper's thread, never the BLUI process.
        if not self.user.SetThreadDpiAwarenessContext(c.c_void_p(-4)):
            raise RuntimeError('Unable to use physical-pixel desktop coordinates')
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.GetWindowsDirectoryW.argtypes = [w.LPWSTR, w.UINT]
        self.kernel.GetWindowsDirectoryW.restype = w.UINT

    def current(self, handle):
        raw = native_windows._identity(self.user, int(handle))
        if raw is None or not raw[2]:
            return None
        pid, thread, started, name = raw
        return state.identity({'handle': str(int(handle)), 'pid': pid, 'thread_id': thread,
                               'process_started': started, 'window_class': name})

    def matches(self, row):
        current = self.current(row['handle'])
        return current is not None and state.key(current) == state.key(row)

    def _safe(self, *rows, marker=False, instance=None):
        if self.abort is not None and self.abort.aborted():
            raise RuntimeError('Desktop recovery requested; stopping further attachment')
        if not all(self.matches(row) for row in rows):
            raise RuntimeError('Desktop window changed before attachment')
        if marker and self.user.GetPropW(int(rows[0]['handle']), MARKER) != 1:
            raise RuntimeError('Desktop canvas marker is missing')
        if instance is not None and self.user.GetPropW(int(rows[0]['handle']), INSTANCE) != int(instance):
            raise RuntimeError('Desktop canvas instance changed before attachment')

    def canvas_matches(self, row):
        return bool(self.matches(row['window']) and
                    self.user.GetPropW(int(row['window']['handle']), INSTANCE) == int(row['instance']))

    def _explorer(self, row):
        windows = c.create_unicode_buffer(32768)
        count = self.kernel.GetWindowsDirectoryW(windows, len(windows))
        executable = native_windows._metadata(row['pid'])['executable']
        return bool(count and count < len(windows) and executable and
                    os.path.normcase(os.path.normpath(executable)) ==
                    os.path.normcase(os.path.join(windows.value, 'explorer.exe')))

    def _child(self, parent, name):
        result = self.user.FindWindowExW(int(parent['handle']), None, name, None)
        if not result or self.user.FindWindowExW(int(parent['handle']), result, name, None):
            return None  # Missing/ambiguous direct child, do not guess.
        child = self.current(result)
        if (child is None or child['window_class'] != name or
                (child['pid'], child['process_started']) != (parent['pid'], parent['process_started']) or
                self.user.GetParent(result) != int(parent['handle'])):
            return None
        return child

    def discover(self):
        root = self.current(self.user.GetShellWindow() or 0)
        if root is None or root['window_class'] != 'Progman' or not self._explorer(root):
            raise RuntimeError('Unable to verify the Windows Explorer desktop')
        candidates = []
        view = self._child(root, 'SHELLDLL_DefView')
        if view is not None:
            candidates.append((root, view))  # Raised Win11/24H2 and legacy Progman.
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        visited = [0]
        def visit(handle, _):
            visited[0] += 1
            if visited[0] > 4096:
                return False
            name = c.create_unicode_buffer(256)
            self.user.GetClassNameW(handle, name, len(name))
            if name.value != 'WorkerW':
                return True
            host = self.current(handle)
            if host is not None and (host['pid'], host['process_started']) == (root['pid'], root['process_started']):
                child = self._child(host, 'SHELLDLL_DefView')
                if child is not None:
                    candidates.append((host, child))
            return True
        self.user.EnumWindows.argtypes, self.user.EnumWindows.restype = [callback_type, w.LPARAM], w.BOOL
        if not self.user.EnumWindows(callback_type(visit), 0) or len(candidates) != 1:
            raise RuntimeError('Windows desktop hierarchy is missing or ambiguous')
        host, view = candidates[0]
        listing = self._child(view, 'SysListView32')
        if listing is None:
            raise RuntimeError('Unable to verify the original Windows desktop icon view')
        row = state.shell_record({'root': root, 'host': host, 'view': view, 'list': listing,
                                  'visible': bool(self.user.IsWindowVisible(int(listing['handle']))),
                                  'raised': bool(self.user.GetWindowLongPtrW(int(root['handle']), -20) &
                                                 WS_EX_NOREDIRECTIONBITMAP)})
        if not self.matches_shell(row):
            raise RuntimeError('Windows desktop changed during discovery')
        return row

    def matches_shell(self, row):
        if row['host']['window_class'] == 'Progman' and state.key(row['host']) != state.key(row['root']):
            return False
        if (not all(self.matches(row[field]) for field in ('root', 'host', 'view', 'list')) or
                self.user.GetShellWindow() != int(row['root']['handle']) or
                self.user.GetParent(int(row['view']['handle'])) != int(row['host']['handle']) or
                self.user.GetParent(int(row['list']['handle'])) != int(row['view']['handle'])):
            return False
        if row['host']['window_class'] == 'WorkerW' and self.user.GetParent(int(row['host']['handle'])):
            return False
        return self._explorer(row['root'])

    def validate_displays(self, rows):
        rows = state.surfaces(rows)
        current = monitors.snapshot()['monitors']
        expected = {row['device']: row['work'] for row in current}
        if len(current) != len(rows) or any(expected.get(row['device']) != row['rect'] for row in rows):
            raise RuntimeError('Display work areas changed; reconnect every desktop canvas')

    def _compatible(self, child, host):
        a = self.user.GetWindowDpiAwarenessContext(int(child['handle']))
        b = self.user.GetWindowDpiAwarenessContext(int(host['handle']))
        if not a or not b or not self.user.AreDpiAwarenessContextsEqual(a, b):
            raise RuntimeError('Desktop and BLUI DPI awareness differ; Windows desktop is preserved')

    def _rect(self, handle):
        rect = w.RECT()
        if not self.user.GetWindowRect(int(handle), c.byref(rect)):
            raise OSError('Unable to read the desktop canvas rectangle')
        return state.rectangle([rect.left, rect.top, rect.right, rect.bottom])

    def capture(self, surface, shell):
        window = self.current(surface['handle'])
        if (window is None or window['window_class'] not in state.CANVAS_CLASSES or
                window['pid'] != self.owner_pid or window['process_started'] != self.owner_started):
            raise RuntimeError('Desktop canvas does not belong to the verified BLUI owner')
        self._safe(window, shell['host'], marker=True)
        if not self.matches_shell(shell):
            raise RuntimeError('Desktop hierarchy changed before capture')
        self._compatible(window, shell['host'])
        handle = int(window['handle'])
        instance = self.user.GetPropW(handle, INSTANCE)
        if not instance or not 0 < instance < 1 << 64:
            raise RuntimeError('Desktop canvas instance marker is missing')
        owner_handle = self.user.GetWindow(handle, 4)  # GW_OWNER, not child GetParent.
        owner = self.current(owner_handle) if owner_handle else None
        if owner_handle and (owner is None or owner['pid'] != self.owner_pid or
                             owner['process_started'] != self.owner_started):
            raise RuntimeError('Desktop canvas has an unexpected foreign owner')
        result = state.canvas_record({'window': window, 'instance': str(instance), 'owner': owner, 'host': shell['host'],
                                    'style': self.user.GetWindowLongPtrW(handle, -16) & 0xffffffff,
                                    'extended_style': self.user.GetWindowLongPtrW(handle, -20) & 0xffffffff,
                                    'rect': self._rect(handle), 'visible': bool(self.user.IsWindowVisible(handle)),
                                    'surface': surface})
        self._safe(window, shell['host'], marker=True, instance=result['instance'])
        if not self.matches_shell(shell):
            raise RuntimeError('Desktop hierarchy changed while capturing rollback')
        return result

    def _long(self, handle, index, value):
        c.set_last_error(0)
        previous = self.user.SetWindowLongPtrW(handle, index, value)
        error = c.get_last_error()
        if not previous and error:
            raise OSError(error, 'Unable to change owned desktop canvas style index ' + str(index))

    def _parent(self, handle, parent):
        c.set_last_error(0)
        previous = self.user.SetParent(handle, parent)
        if not previous and c.get_last_error():
            raise OSError('Unable to parent the owned desktop canvas')
        # With NULL new parent and WS_CHILD still set, Windows may report the
        # desktop HWND until the caller restores WS_POPUP/non-child styles.
        # SetParent does not change these bits itself (documented contract).
        return parent is None or self.user.GetParent(handle) == parent

    def attach(self, row, shell):
        window, host = row['window'], shell['host']
        self._safe(window, host, marker=True, instance=row['instance'])
        if not self.matches_shell(shell):
            return False
        self._compatible(window, host)
        handle, parent = int(window['handle']), int(host['handle'])
        # Only OWN HWND style/z-order changes. No foreign WorkerW restacking.
        style = (row['style'] & ~(WS_POPUP | 0xc00000 | 0x40000 | 0x80000 | 0x30000)) | WS_CHILD | 0x4000000
        extended = (row['extended_style'] & ~(0x40000 | 0x8 | 0x8000000 | 0x20)) | 0x80
        if shell['raised']:
            extended |= WS_EX_LAYERED
        self._long(handle, -16, style)
        self._safe(window, host, marker=True, instance=row['instance'])
        self._long(handle, -20, extended)
        self._safe(window, host, marker=True, instance=row['instance'])
        if shell['raised'] and not self.user.SetLayeredWindowAttributes(handle, 0, 255, 2):
            raise OSError('The raised Windows desktop cannot render this canvas safely')
        self._safe(window, host, marker=True, instance=row['instance'])
        self._compatible(window, host)
        if not self._parent(handle, parent):
            return False
        left, top, right, bottom = row['surface']['rect']
        points = (w.POINT * 2)(w.POINT(left, top), w.POINT(right, bottom))
        c.set_last_error(0)
        if not self.user.MapWindowPoints(None, parent, points, 2) and c.get_last_error():
            raise OSError('Unable to map desktop work-area coordinates')
        client = w.RECT()
        if (not self.user.GetClientRect(parent, c.byref(client)) or
                points[0].x < 0 or points[0].y < 0 or
                points[1].x > client.right or points[1].y > client.bottom):
            raise RuntimeError('Windows desktop host does not cover every display')
        self._safe(window, host, marker=True, instance=row['instance'])
        # HWND_TOP here is a sibling position under Explorer, not global TOPMOST.
        result = self.user.SetWindowPos(handle, None, points[0].x, points[0].y,
            points[1].x - points[0].x, points[1].y - points[0].y, 0x4000 | 0x10 | 0x20 | 0x40 | 0x200)
        return bool(result and self.attached(row, shell))

    def attached(self, row, shell):
        return bool(self.canvas_matches(row) and self.matches_shell(shell) and
                    self.user.GetParent(int(row['window']['handle'])) == int(shell['host']['handle']) and
                    self.user.GetWindowLongPtrW(int(row['window']['handle']), -16) & WS_CHILD and
                    self.user.GetPropW(int(row['window']['handle']), MARKER) == 1)

    def hide_icons(self, shell):
        if not shell['visible']:
            return self.matches_shell(shell)  # Preserve a desktop already hidden by the user.
        self._safe(shell['list'])
        if not self.matches_shell(shell):
            return False
        handle = int(shell['list']['handle'])
        if not self.user.IsWindowVisible(handle):
            return True
        return bool(self.user.SetWindowPos(handle, None, 0, 0, 0, 0,
                                          0x4000 | 0x1 | 0x2 | 0x4 | 0x10 | 0x200 | 0x80))

    def restore_icons(self, shell):
        if not shell['visible'] or not self.matches_shell(shell):
            return True  # Lost/reused HWNDs never receive a stale visibility action.
        handle = int(shell['list']['handle'])
        if self.user.IsWindowVisible(handle):
            return True
        if not self.matches_shell(shell):
            return True
        self.user.SetWindowPos(handle, None, 0, 0, 0, 0,
                               0x4000 | 0x1 | 0x2 | 0x4 | 0x10 | 0x200 | 0x40)
        return bool(self.matches_shell(shell) and self.user.IsWindowVisible(handle))

    def restore_canvas(self, row):
        self.restore_error = ''
        window = row['window']
        if not self.canvas_matches(row):
            return True  # Owner exited/Explorer destroyed child; no live HWND to restore.
        handle = int(window['handle'])
        is_child = bool(self.user.GetWindowLongPtrW(handle, -16) & WS_CHILD)
        if is_child:
            current_parent = self.user.GetParent(handle)
            desktop_parent = self.user.GetDesktopWindow()
            if current_parent and current_parent != desktop_parent and (
                    current_parent != int(row['host']['handle']) or not self.matches(row['host'])):
                return False  # Never detach from an unrelated/reused new parent.
        if not self.canvas_matches(row):
            return True
        try:
            if is_child and not self._parent(handle, None):
                return False
            if not self.canvas_matches(row):
                return True
            if self.user.GetWindowLongPtrW(handle, -16) & 0xffffffff != row['style']:
                self._long(handle, -16, row['style'])
            if not self.canvas_matches(row):
                return True
            if self.user.GetWindowLongPtrW(handle, -20) & 0xffffffff != row['extended_style']:
                self._long(handle, -20, row['extended_style'])
            owner = row['owner']
            if not self.canvas_matches(row):
                return True
            expected_owner = int(owner['handle']) if owner and self.matches(owner) else 0
            if int(self.user.GetWindow(handle, 4) or 0) != expected_owner:
                self._long(handle, -8, expected_owner)
            left, top, right, bottom = row['rect']
            if not self.canvas_matches(row):
                return True
            flags = 0x4000 | 0x4 | 0x10 | 0x20 | 0x200 | (0x40 if row['visible'] else 0x80)
            if not self.user.SetWindowPos(handle, None, left, top, right - left, bottom - top, flags):
                self.restore_error = 'Desktop canvas position restoration failed: ' + str(c.get_last_error())
                return False
            if self.canvas_matches(row) and self._rect(handle) != row['rect']:
                self.restore_error = 'Desktop canvas geometry restoration pending'
                return False  # ASYNCWINDOWPOS may need a native message-loop turn.
            return (self.canvas_matches(row) and
                    not self.user.GetWindowLongPtrW(handle, -16) & WS_CHILD and
                    int(self.user.GetWindow(handle, 4) or 0) == expected_owner and
                    self.user.GetWindowLongPtrW(handle, -16) & 0xffffffff == row['style'] and
                    self.user.GetWindowLongPtrW(handle, -20) & 0xffffffff == row['extended_style'])
        except OSError as exc:
            self.restore_error = str(exc)[:2048]
            return False
