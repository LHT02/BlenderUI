# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolated real Shell_NotifyIcon listener, preserving the existing Explorer tray.

Only explicitly starting this helper broadcasts TaskbarCreated. It registers its
OWN hidden shell-compatible receiver, forwards packets to verified Explorer, and
destroys its OWN windows before broadcasting restoration on EOF/owner death.
No injection, remote-memory access, Explorer restacking or persistent settings.
Design references (independent implementation): RetroBar / ManagedShell TrayService.
"""
import ctypes as c
from ctypes import wintypes as w
import json
import os
import queue
import sys
import threading
import time

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blui_desktop import native_windows, notification_pixels, notification_protocol as protocol
from blui_desktop.taskbar_native import OwnerProcess

MAX_COMMAND = 8192
WM_COPYDATA, WM_USER = 0x4a, 0x400


class _CopyData(c.Structure):
    _fields_ = [('kind', c.c_size_t), ('size', w.DWORD), ('data', c.c_void_p)]


def _api():
    user = native_windows._api()
    for name, result, args in (
        ('RegisterClassW', w.WORD, [c.c_void_p]),
        ('UnregisterClassW', w.BOOL, [w.LPCWSTR, w.HINSTANCE]),
        ('CreateWindowExW', w.HWND, [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
            c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]),
        ('DestroyWindow', w.BOOL, [w.HWND]),
        ('DefWindowProcW', c.c_ssize_t, [w.HWND, w.UINT, w.WPARAM, w.LPARAM]),
        ('SetWindowPos', w.BOOL, [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]),
        ('FindWindowW', w.HWND, [w.LPCWSTR, w.LPCWSTR]),
        ('PostMessageW', w.BOOL, [w.HWND, w.UINT, w.WPARAM, w.LPARAM]),
        ('SendMessageTimeoutW', c.c_ssize_t, [w.HWND, w.UINT, w.WPARAM, w.LPARAM,
            w.UINT, w.UINT, c.POINTER(c.c_size_t)]),
        ('SendNotifyMessageW', w.BOOL, [w.HWND, w.UINT, w.WPARAM, w.LPARAM]),
        ('RegisterWindowMessageW', w.UINT, [w.LPCWSTR]),
        ('AllowSetForegroundWindow', w.BOOL, [w.DWORD]),
        ('PeekMessageW', w.BOOL, [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]),
        ('TranslateMessage', w.BOOL, [c.POINTER(w.MSG)]),
        ('DispatchMessageW', c.c_ssize_t, [c.POINTER(w.MSG)]),
    ):
        function = getattr(user, name)
        function.restype, function.argtypes = result, args
    return user


class Host:
    def __init__(self, *, private=False):
        self.private = bool(private)
        self.user = _api()
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.GetModuleHandleW.argtypes, self.kernel.GetModuleHandleW.restype = [w.LPCWSTR], w.HMODULE
        self.kernel.GetWindowsDirectoryW.argtypes, self.kernel.GetWindowsDirectoryW.restype = [w.LPWSTR, w.UINT], w.UINT
        self.kernel.CreateMutexW.argtypes, self.kernel.CreateMutexW.restype = [c.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        self.instance = self.kernel.GetModuleHandleW(None)
        self.tray = self.notify = self.lock = None
        self.original = None
        self.broadcasted = False
        self.error = ''
        self.classes = []
        self.next_check = 0
        self.store = protocol.Store(lambda handle: native_windows._identity(self.user, handle), notification_pixels.extract)
        self._wndproc_type = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        self._wndproc = self._wndproc_type(self._message)

    def _explorer(self, handle):
        identity = native_windows._identity(self.user, handle)
        if identity is None or identity[3] != 'Shell_TrayWnd':
            return None
        path = native_windows._metadata(identity[0]).get('executable', '')
        directory = c.create_unicode_buffer(32768)
        if not self.kernel.GetWindowsDirectoryW(directory, len(directory)):
            return None
        expected = os.path.join(directory.value, 'explorer.exe')
        if (os.path.normcase(os.path.normpath(path)) != os.path.normcase(os.path.normpath(expected)) or
                native_windows._identity(self.user, handle) != identity):
            return None
        return handle, identity

    def _find_explorer(self):
        values = []
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def visit(handle, _parameter):
            if handle != self.tray:
                value = self._explorer(handle)
                if value:
                    values.append(value)
            return len(values) < 2
        self.user.EnumWindows.argtypes, self.user.EnumWindows.restype = [callback_type, w.LPARAM], w.BOOL
        self.user.EnumWindows(callback_type(visit), 0)
        return values[0] if values else None

    def _register(self, name):
        prototype = self._wndproc_type
        class WndClass(c.Structure):
            _fields_ = [('style', w.UINT), ('procedure', prototype), ('class_extra', c.c_int),
                        ('window_extra', c.c_int), ('instance', w.HINSTANCE), ('icon', w.HICON),
                        ('cursor', w.HANDLE), ('background', w.HBRUSH), ('menu', w.LPCWSTR),
                        ('name', w.LPCWSTR)]
        descriptor = WndClass(8, self._wndproc, 0, 0, self.instance, None, None, None, None, name)
        if not self.user.RegisterClassW(c.byref(descriptor)):
            raise OSError('Unable to register notification receiver class')
        self.classes.append(name)

    def _own(self):
        identity = native_windows._identity(self.user, self.tray)
        name = 'BLUI_QA_NotificationHost' if self.private else 'Shell_TrayWnd'
        return bool(identity and identity[0] == os.getpid() and identity[3] == name)

    def open(self):
        if not self.private:
            c.set_last_error(0)
            self.lock = self.kernel.CreateMutexW(None, False, 'Local\\BLUI.NotificationHost.v1')
            if not self.lock or c.get_last_error() == 183:
                raise RuntimeError('Another BLUI notification host is already running')
            first = self.user.FindWindowW('Shell_TrayWnd', None)
            self.original = self._explorer(first) if first else None
            if first and self.original is None:
                raise RuntimeError('Another notification-area host is already active')
        name = 'BLUI_QA_NotificationHost' if self.private else 'Shell_TrayWnd'
        child_name = 'BLUI_QA_TrayNotifyWnd' if self.private else 'TrayNotifyWnd'
        self._register(name)
        self._register(child_name)
        # Intentionally NOT WS_VISIBLE: this is a receiver, never a blank BLUI UI window.
        self.tray = self.user.CreateWindowExW(0x08000088, name, '', 0x86000000,
                                             0, 0, 1, 1, None, None, self.instance, None)
        if not self.tray:
            raise OSError('Unable to create notification receiver')
        self.notify = self.user.CreateWindowExW(0, child_name, '', 0x46000000,
                                               0, 0, 1, 1, self.tray, None, self.instance, None)
        if not self.notify:
            raise OSError('Unable to create notification child receiver')
        self._raise_own()
        if not self.private:
            if self.user.FindWindowW('Shell_TrayWnd', None) != self.tray:
                raise RuntimeError('Windows did not select the BLUI notification receiver')
            self._broadcast()
            self.broadcasted = True

    def _raise_own(self):
        if not self._own():
            raise RuntimeError('The notification receiver identity changed')
        if not self.user.SetWindowPos(self.tray, -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10 | 0x200):
            raise OSError('Unable to position the notification receiver')

    def _broadcast(self):
        message = self.user.RegisterWindowMessageW('TaskbarCreated')
        if message:
            self.user.SendNotifyMessageW(0xffff, message, 0, 0)

    def _forward(self, message, wparam, lparam):
        if self.private:
            return 0
        if self.original is None or native_windows._identity(self.user, self.original[0]) != self.original[1]:
            self.original = self._find_explorer()
        if self.original is None:
            return 0
        handle, identity = self.original
        if native_windows._identity(self.user, handle) != identity:
            return 0
        result = c.c_size_t()
        # A hung Explorer can delay only this isolated host, bounded to 250ms.
        if self.user.SendMessageTimeoutW(handle, message, wparam, lparam, 0x3, 250, c.byref(result)):
            return c.c_ssize_t(result.value).value
        return 0

    def _message(self, handle, message, wparam, lparam):
        try:
            if message == WM_COPYDATA and lparam:
                copy = c.cast(lparam, c.POINTER(_CopyData)).contents
                if not 0 < copy.size <= protocol.MAX_PACKET or not copy.data:
                    return 0
                accepted = False
                if copy.kind == 1:
                    try:
                        packet = protocol.parse(c.string_at(copy.data, copy.size))
                        accepted = self.store.apply(packet)
                    except (ValueError, OSError):
                        pass
                # AppBar/GetRect/balloon packets remain Explorer's responsibility.
                forwarded = self._forward(message, wparam, lparam)
                return forwarded or int(accepted)
            # Known shell broadcast requiring asynchronous forwarding, not foreign pointer data.
            if message == WM_USER + 372:
                return self._forward(message, wparam, lparam)
        except Exception as exc:
            self.error = str(exc)[:1024]
            return 0
        return self.user.DefWindowProcW(handle, message, wparam, lparam)

    def command(self, value):
        if not isinstance(value, dict) or value.get('command') not in ('activate', 'shutdown', 'snapshot', 'heartbeat'):
            raise ValueError('Invalid notification command')
        command = value['command']
        if command == 'activate':
            token = value.get('key')
            if not isinstance(token, str) or len(token) > 128:
                raise ValueError('Invalid notification identity')
            self.store.action(token, value.get('event'), value.get('x'), value.get('y'),
                              self.user.PostMessageW, self.user.AllowSetForegroundWindow)
        return command != 'shutdown'

    def pump(self, now):
        message = w.MSG()
        for _ in range(128):
            if not self.user.PeekMessageW(c.byref(message), None, 0, 0, 1):
                break
            self.user.TranslateMessage(c.byref(message))
            self.user.DispatchMessageW(c.byref(message))
        if now >= self.next_check:
            self.store.prune()
            if not self.private and self.user.FindWindowW('Shell_TrayWnd', None) != self.tray:
                self._raise_own()
            self.next_check = now + 2

    def snapshot(self, enabled=True):
        return {'enabled': bool(enabled), 'error': self.error, 'revision': self.store.revision,
                'icons': self.store.snapshot() if enabled else [], 'host_handle': str(self.tray or 0)}

    def close(self):
        # Only handles created by this helper are ever destroyed or restacked.
        if self.notify:
            self.user.DestroyWindow(self.notify)
            self.notify = None
        if self.tray:
            self.user.DestroyWindow(self.tray)
            self.tray = None
        for name in reversed(self.classes):
            self.user.UnregisterClassW(name, self.instance)
        self.classes.clear()
        if self.broadcasted:
            self._broadcast()
            self.broadcasted = False
        if self.lock:
            self.kernel.CloseHandle(self.lock)
            self.lock = None


def run(pid, started, *, private=False):
    if os.name != 'nt' or pid != os.getppid():
        raise ValueError('Invalid notification host owner')
    # Windows pipe encoding must not depend on the user's legacy code page.
    sys.stdout.reconfigure(encoding='utf-8', errors='strict', newline='\n')
    inbox, output = queue.Queue(maxsize=32), queue.Queue(maxsize=2)
    eof = threading.Event()
    final_sent = threading.Event()
    host = owner = None
    def reader():
        try:
            while True:
                line = sys.stdin.buffer.readline(MAX_COMMAND + 1)
                if not line or len(line) > MAX_COMMAND or not line.endswith(b'\n'):
                    break
                try:
                    value = json.loads(line)
                    inbox.put_nowait(value)
                    if isinstance(value, dict) and value.get('command') == 'shutdown':
                        # Do not enter another buffered stdin read after shutdown:
                        # its lock can stall Python finalization while the parent
                        # intentionally retains the pipe to read our final status.
                        break
                except (ValueError, queue.Full):
                    continue
        finally:
            eof.set()
    def writer():
        while True:
            value = output.get()
            if value is None:
                return
            try:
                sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
                sys.stdout.flush()
                if value.get('enabled') is False:
                    final_sent.set()
            except (OSError, ValueError):
                eof.set()
                final_sent.set()
                return
    def publish(value):
        try:
            output.put_nowait(value)
        except queue.Full:
            try:
                output.get_nowait()
                output.put_nowait(value)
            except queue.Empty:
                pass
    threading.Thread(target=reader, name='BLUI notification requests', daemon=True).start()
    threading.Thread(target=writer, name='BLUI notification snapshots', daemon=True).start()
    try:
        owner = OwnerProcess(pid, started)
        host = Host(private=private)
        host.open()
        revision, last_emit = -1, 0
        while owner.alive() and not eof.is_set():
            now = time.monotonic()
            host.pump(now)
            while not inbox.empty():
                command = inbox.get_nowait()
                try:
                    if not host.command(command):
                        eof.set()
                        break
                except (ValueError, OSError) as exc:
                    host.error = str(exc)[:1024]
            if revision != host.store.revision or now - last_emit > 2:
                publish(host.snapshot())
                revision, last_emit = host.store.revision, now
            time.sleep(.02)  # Only this disposable helper, never Blender's UI thread.
    except (OSError, ValueError, RuntimeError) as exc:
        if host:
            host.error = str(exc)[:1024]
        publish({'enabled': False, 'error': str(exc)[:1024], 'revision': 0, 'icons': [], 'host_handle': '0'})
    finally:
        if host:
            host.close()
            publish(host.snapshot(enabled=False))
        if owner:
            owner.close()
        # All native teardown/restoration is complete before this bounded wait.
        final_sent.wait(.25)


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and sys.argv[3] != '--qa-private'):
        raise SystemExit('Usage: notification_host.py <owner-pid> <owner-start> [--qa-private]')
    run(int(sys.argv[1]), sys.argv[2], private=len(sys.argv) == 4)
    # Only this disposable helper, AFTER own HWND teardown and restoration.
    # A dead parent's pipe/daemon reader must not delay interpreter shutdown.
    os._exit(0)
