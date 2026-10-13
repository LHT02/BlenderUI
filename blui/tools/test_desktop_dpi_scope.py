# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only source and fake fixture-DPI checks; never opens/changes native windows."""
import ast
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


class DesktopDpiScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = source('intern/ghost/intern/GHOST_BluiDesktopDpiWin32.hh')
        cls.system = source('intern/ghost/intern/GHOST_SystemWin32.cc')

    def test_creation_scope_is_desktop_only_and_closes_before_window_registration(self):
        create = self.system[self.system.index('GHOST_IWindow *GHOST_SystemWin32::createWindow('):]
        create = create[:create.index('GHOST_IContext *GHOST_SystemWin32::createOffscreenContext(')]
        self.assertIn('GHOST_BluiDesktopDpiScope desktop_dpi((glSettings.flags & GHOST_glBluiDesktopWindow) != 0)', create)
        self.assertLess(create.index('if (!desktop_dpi.ready())'), create.index('new GHOST_WindowWin32('))
        self.assertLess(create.index('if (!desktop_dpi.window_matches'), create.index('m_windowManager->addWindow'))
        self.assertIn('  }\n\n  if (window->getValid())', create)
        self.assertNotIn('SetProcessDpi', self.scope)
        self.assertNotIn('SetThreadDpiHostingBehavior', self.scope)

    def test_modern_api_resolution_preserves_old_target_and_fails_closed(self):
        self.assertIn('GetModuleHandleW(L"user32.dll")', self.scope)
        for api in ('GetWindowDpiAwarenessContext', 'GetThreadDpiAwarenessContext',
                    'SetThreadDpiAwarenessContext', 'AreDpiAwarenessContextsEqual'):
            self.assertIn('GetProcAddress(user, "' + api + '")', self.scope)
        self.assertIn('using SetContextFn = HANDLE(WINAPI *)(HANDLE)', self.scope)
        self.assertIn('!m_window_context || !m_thread_context || !m_set_context || !m_equal_context', self.scope)
        self.assertNotIn('LoadLibrary', self.scope)
        self.assertNotIn('#define _WIN32_WINNT', self.scope)

    def test_raii_restores_exact_old_thread_and_closes_read_only_process(self):
        self.assertIn('m_previous = m_set_context(m_context)', self.scope)
        self.assertIn('if (m_previous && !m_set_context(m_previous))', self.scope)
        self.assertIn('CloseHandle(m_process)', self.scope)
        self.assertIn('GHOST_BluiDesktopDpiScope(const GHOST_BluiDesktopDpiScope &) = delete', self.scope)

    def test_trusted_explorer_path_and_live_process_epoch_are_required(self):
        for check in ('GetShellWindow()', 'L"Progman"', 'GetWindowsDirectoryW',
                      'QueryFullProcessImageNameW', 'expected += L"\\\\explorer.exe"',
                      '_wcsicmp', 'PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE',
                      'WaitForSingleObject(m_process, 0) == WAIT_TIMEOUT',
                      'started.dwLowDateTime == m_started.dwLowDateTime',
                      'started.dwHighDateTime == m_started.dwHighDateTime'):
            self.assertIn(check, self.scope)

    def test_unique_bounded_exact_native_parent_chain(self):
        for check in ('m_visited > 4096', 'm_candidates != 1', 'L"WorkerW"',
                      'L"SHELLDLL_DefView"', 'L"SysListView32"',
                      'GetParent(handle) == parent.handle',
                      '!FindWindowExW(parent.handle, handle, name, nullptr)',
                      'current.thread == saved.thread', 'pid != m_pid'):
            self.assertIn(check, self.scope)
        for mutation in ('SetParent(', 'ShowWindow(', 'SetWindowPos(', 'SendMessage',
                         'TerminateProcess', 'WriteProcessMemory'):
            self.assertNotIn(mutation, self.scope)

    def test_helper_compatibility_guard_was_not_relaxed(self):
        helper = source('scripts/modules/blui_desktop/desktop_host_native.py')
        start = helper.index('    def _compatible(')
        end = helper.index('    def _rect(', start)
        check = helper[start:end]
        self.assertIn('not self.user.AreDpiAwarenessContextsEqual(a, b)', check)
        self.assertIn('Desktop and BLUI DPI awareness differ', check)

    def test_all_real_fixtures_preserve_ui_thread_before_native_desktop_creation(self):
        for name in ('host', 'service', 'hover_restore'):
            fixture = source('blui/tools/check_desktop_' + name + '_native.py')
            self.assertIn('DesktopDpiQA()', fixture)
            self.assertIn('dpi_qa.discovery()', fixture)
            self.assertIn('dpi_qa.unchanged()', fixture)
            self.assertIn('dpi_qa.compatible(', fixture)
        lifecycle = source('blui/tools/check_desktop_native_lifecycle.py')
        self.assertIn('with dpi_qa.matching_owned_window(handle):\n                parent = int(user.CreateWindowExW', lifecycle)
        self.assertNotIn('with dpi_qa.matching_owned_window(handle):\n        assert bpy.ops.wm.blui_shell_window_create', lifecycle)


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class FixtureDpiTests(unittest.TestCase):
    def setUp(self):
        self.thread = 2
        self.contexts = {10: 2, 20: 4, 30: 4}
        self.user = SimpleNamespace(
            GetThreadDpiAwarenessContext=Function(lambda: self.thread),
            SetThreadDpiAwarenessContext=Function(self.set_thread),
            GetWindowDpiAwarenessContext=Function(lambda handle: self.contexts[handle]),
            AreDpiAwarenessContextsEqual=Function(lambda a, b: a == b))
        window = SimpleNamespace(blui_shell_role='NORMAL', blui_native_handle='10', as_pointer=lambda: 100)
        bpy = SimpleNamespace(context=SimpleNamespace(window_manager=SimpleNamespace(windows=[window])))
        self.native = SimpleNamespace(_api=lambda: self.user, _identity=self.identity)
        tree = ast.parse(source('blui/tools/qa_desktop_dpi.py'))
        node = next(item for item in tree.body if isinstance(item, ast.ClassDef))
        namespace = dict(contextmanager=contextmanager, c=c, w=w, os=os, bpy=bpy, native_windows=self.native)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual private DPI fixture helper>', 'exec'), namespace)
        self.qa = namespace['DesktopDpiQA']()

    def identity(self, _user, handle):
        return (os.getpid() if handle != 30 else os.getpid() + 1, 1, 'started', 'class')

    def set_thread(self, context):
        old, self.thread = self.thread, context
        return old

    def test_discovery_worker_context_is_restored_even_on_exception(self):
        with self.assertRaisesRegex(ValueError, 'fixture error'):
            with self.qa.preserved():
                self.thread = 4
                raise ValueError('fixture error')
        self.assertEqual(self.thread, 2)
        self.qa.unchanged()

    def test_new_owned_fake_parent_creation_matches_then_restores_original_thread(self):
        with self.qa.matching_owned_window(20):
            self.assertEqual(self.thread, 4)
        self.assertEqual(self.thread, 2)
        self.qa.unchanged()

    def test_foreign_window_cannot_supply_creation_scope(self):
        with self.assertRaisesRegex(AssertionError, 'OWN'):
            with self.qa.matching_owned_window(30):
                self.fail('Foreign DPI scope must not enter')
        self.assertEqual(self.thread, 2)

    def test_existing_normal_context_change_is_not_masked_by_thread_restoration(self):
        self.contexts[10] = 4
        with self.assertRaisesRegex(AssertionError, 'existing NORMAL DPI'):
            self.qa.unchanged()


if __name__ == '__main__':
    unittest.main(verbosity=2)
