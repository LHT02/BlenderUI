# SPDX-License-Identifier: GPL-2.0-or-later
"""ROOT-only native fixture DPI assertions; no import-time native operations."""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import os
import bpy
from blui_desktop import native_windows


class DesktopDpiQA:
    def __init__(self):
        self.user = native_windows._api()
        for name, result, args in (
            ('GetThreadDpiAwarenessContext', c.c_void_p, []),
            ('SetThreadDpiAwarenessContext', c.c_void_p, [c.c_void_p]),
            ('GetWindowDpiAwarenessContext', c.c_void_p, [w.HWND]),
            ('AreDpiAwarenessContextsEqual', w.BOOL, [c.c_void_p, c.c_void_p]),
        ):
            function = getattr(self.user, name)
            function.restype, function.argtypes = result, args
        self.thread = self.user.GetThreadDpiAwarenessContext()
        assert self.thread, 'Native fixture thread DPI context is unavailable'
        self.normal = {}
        for window in bpy.context.window_manager.windows:
            if window.blui_shell_role != 'NORMAL':
                continue
            handle = int(window.blui_native_handle)
            identity = native_windows._identity(self.user, handle)
            assert identity and identity[0] == os.getpid()
            self.normal[(window.as_pointer(), window.blui_native_handle)] = (
                identity, self.user.GetWindowDpiAwarenessContext(handle))
        assert self.normal, 'Native DPI QA needs an owned NORMAL baseline'

    @contextmanager
    def preserved(self):
        original = self.user.GetThreadDpiAwarenessContext()
        try:
            yield
        finally:
            assert self.user.SetThreadDpiAwarenessContext(original)
            self.unchanged()

    @contextmanager
    def matching_owned_window(self, handle):
        identity = native_windows._identity(self.user, handle)
        assert identity and identity[0] == os.getpid(), 'DPI scope may only read OWN fixture window'
        context = self.user.GetWindowDpiAwarenessContext(handle)
        assert context
        previous = self.user.SetThreadDpiAwarenessContext(context)
        assert previous
        try:
            yield
        finally:
            assert self.user.SetThreadDpiAwarenessContext(previous)
            self.unchanged()

    def discovery(self):
        from blui_desktop import desktop_host_native, monitors
        # These APIs normally run only in dedicated service processes. Keep
        # temporary worker context from influencing production-window creation.
        with self.preserved():
            backend = desktop_host_native.DesktopWindows()
            original = backend.discover()
            snapshot = monitors.snapshot()
        print('DESKTOP_DPI_BASELINE:', {'thread': self.thread,
              'normal_contexts': [row[1] for row in self.normal.values()],
              'host_context': self.user.GetWindowDpiAwarenessContext(int(original['host']['handle']))}, flush=True)
        return backend, original, snapshot

    def unchanged(self):
        assert self.user.AreDpiAwarenessContextsEqual(
            self.user.GetThreadDpiAwarenessContext(), self.thread), 'Desktop creation changed UI thread DPI'
        current = {(window.as_pointer(), window.blui_native_handle): window
                   for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL'}
        assert set(current) == set(self.normal), 'Desktop DPI scope must not replace NORMAL windows'
        for token, (identity, context) in self.normal.items():
            handle = int(token[1])
            assert native_windows._identity(self.user, handle) == identity
            assert self.user.AreDpiAwarenessContextsEqual(
                self.user.GetWindowDpiAwarenessContext(handle), context), 'Desktop scope changed existing NORMAL DPI'

    def compatible(self, child, host):
        self.unchanged()
        identity = native_windows._identity(self.user, child)
        assert identity and identity[0] == os.getpid()
        a, b = self.user.GetWindowDpiAwarenessContext(child), self.user.GetWindowDpiAwarenessContext(host)
        print('DESKTOP_DPI_CREATED:', {'child': str(child), 'child_context': a,
                                      'host_context': b, 'ui_thread': self.user.GetThreadDpiAwarenessContext()}, flush=True)
        assert a and b and self.user.AreDpiAwarenessContextsEqual(a, b), 'New Desktop must inherit verified host DPI'
