# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure native-role lifecycle tests using simulated bpy windows, never Win32 mutations."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import monitors, window_placement


class Window:
    next_id = 1

    def __init__(self, role):
        self.number = Window.next_id
        Window.next_id += 1
        self.blui_shell_role = role
        self.blui_is_taskbar = role == 'TASKBAR'
        self.blui_native_handle = str(self.number)
        area = SimpleNamespace(regions=[SimpleNamespace(type='WINDOW')], tag_redraw=lambda: None)
        self.screen = SimpleNamespace(areas=[area])

    def as_pointer(self):
        return self.number


def display(device, x, primary=False, dpi=96):
    return {'device': device, 'rect': [x, 0, x + 1920, 1080],
            'work': [x, 0, x + 1920, 1040], 'dpi': [dpi, dpi], 'primary': primary}


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.windows = [Window('NORMAL')]
        context = SimpleNamespace(window_manager=SimpleNamespace(windows=self.windows), window=self.windows[0])
        context.preferences = SimpleNamespace(view=SimpleNamespace(ui_scale=1.0))
        test = self
        class Override:
            def __init__(self, **values):
                self.previous = context.window
                self.window = values['window']
            def __enter__(self):
                context.window = self.window
            def __exit__(self, *args):
                context.window = self.previous
        context.temp_override = Override
        self.context = context
        self.settings = mock.patch('blui_desktop.taskbar_settings.values', return_value={
            'version': 1, 'revision': 0, 'height': 56, 'icon_size': 32}).start()
        self.created = []
        self.closed = []
        def create(**values):
            window = Window(values['role'])
            self.windows.append(window)
            self.created.append(window)
            return {'FINISHED'}
        def close(**values):
            self.closed.append(context.window)
            self.windows.remove(context.window)
            return {'FINISHED'}
        bpy = ModuleType('bpy')
        bpy.context = context
        bpy.ops = SimpleNamespace(wm=SimpleNamespace(blui_shell_window_create=create, window_close=close))
        runtime = ModuleType('blui_desktop.runtime')
        runtime.monitor_snapshot = lambda: test.snapshot
        runtime.interaction_busy = lambda _tree: False
        localization = ModuleType('blui_explorer.localization')
        localization.iface = lambda text: text
        self.snapshot = {'coordinate_space': 'physical', 'monitors': [display('LEFT', -1920), display('RIGHT', 0, True, 144)]}
        patcher = mock.patch.dict(sys.modules, {'bpy': bpy, 'blui_desktop.runtime': runtime,
                                               'blui_explorer.localization': localization})
        patcher.start()
        self.addCleanup(patcher.stop)
        import blui_desktop
        package = mock.patch.multiple(blui_desktop, runtime=runtime, create=True)
        package.start()
        self.addCleanup(package.stop)
        path = Path(__file__).resolve().parents[2] / 'scripts/modules/blui_desktop/taskbar_windows.py'
        specification = importlib.util.spec_from_file_location('blui_desktop._test_taskbar_windows', path)
        self.module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(self.module)
        for function in ('_topmost', 'focus_window', '_reserve'):
            patcher = mock.patch.object(self.module, function, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.place = mock.patch.object(window_placement, 'place', return_value=True).start()
        def bounds(handle):
            window = next(item for item in self.windows if item.blui_native_handle == handle)
            monitor = next(row for row in self.snapshot['monitors'] if row['device'] == self.module.device(window))
            return {'rect': self.module.bar_rect(monitor)}
        mock.patch.object(window_placement, 'bounds', side_effect=bounds).start()
        self.recover = mock.patch.object(window_placement, 'recover', return_value=False).start()
        self.addCleanup(mock.patch.stopall)

    def test_one_role_bar_per_monitor_and_no_default_workspace_change(self):
        values = self.module.open_for_displays(self.context)
        self.assertEqual(len(values), 2)
        self.assertEqual(len(self.created), 2)
        self.assertEqual(self.windows[0].blui_shell_role, 'NORMAL')
        self.assertEqual({self.module.device(window) for window in values}, {'LEFT', 'RIGHT'})

    def test_repeated_open_reuses_each_live_bar(self):
        first = self.module.open_for_displays(self.context)
        second = self.module.open_for_displays(self.context)
        self.assertEqual(first, second)
        self.assertEqual(len(self.created), 2)

    def test_request_without_monitor_snapshot_is_serviced_later(self):
        self.snapshot = {'coordinate_space': 'physical', 'monitors': []}
        self.assertEqual(self.module.open_for_displays(self.context), [])
        self.assertTrue(self.module.needs_service())
        self.snapshot = {'coordinate_space': 'physical', 'monitors': [display('MAIN', 0, True)]}
        self.module.tick(self.snapshot)
        self.assertEqual(len(self.created), 1)
        self.assertFalse(self.module._pending)

    def test_primary_display_switch_closes_only_secondary_bar(self):
        self.module.open_for_displays(self.context)
        self.module.open_for_displays(self.context, all_displays=False)
        self.assertEqual([self.module.device(window) for window in self.module.role_windows('TASKBAR')], ['RIGHT'])
        self.assertEqual(len(self.closed), 1)
        self.assertTrue(self.windows[0].blui_shell_role == 'NORMAL')

    def test_disconnect_retires_only_own_disconnected_bar(self):
        self.module.open_for_displays(self.context)
        self.snapshot = {'coordinate_space': 'physical', 'monitors': [display('RIGHT', 0, True)]}
        self.module.tick(self.snapshot)
        self.assertEqual(len(self.closed), 1)
        self.assertEqual(self.closed[0].blui_shell_role, 'TASKBAR')
        self.assertEqual(len(self.module.role_windows('TASKBAR')), 1)

    def test_busy_topology_change_retries_after_interaction_releases(self):
        self.module.open_for_displays(self.context)
        previous = self.module._topology
        self.snapshot = {'coordinate_space': 'physical', 'monitors': [display('RIGHT', 0, True)]}
        with mock.patch.object(self.module.runtime, 'interaction_busy', return_value=True):
            self.module.tick(self.snapshot)
        self.assertEqual(self.module._topology, previous)
        self.assertEqual(len(self.module.role_windows('TASKBAR')), 2)
        self.module.tick(self.snapshot)
        self.assertEqual(len(self.module.role_windows('TASKBAR')), 1)
        self.assertNotEqual(self.module._topology, previous)

    def test_steady_tick_never_issues_window_placement_syscalls(self):
        self.module.open_for_displays(self.context)
        self.place.reset_mock()
        self.module.tick(self.snapshot)
        self.place.assert_not_called()
        self.recover.assert_not_called()

    def test_failed_new_bar_placement_rolls_back_only_created_role_window(self):
        self.place.side_effect = OSError('test placement failed')
        with self.assertRaises(OSError):
            self.module.open_for_displays(self.context)
        self.assertEqual(len(self.windows), 1)
        self.assertEqual(self.windows[0].blui_shell_role, 'NORMAL')
        self.assertEqual(len(self.closed), 1)
        self.assertTrue(self.module.needs_service())
        self.place.side_effect = None
        self.module.tick(self.snapshot)
        self.assertFalse(self.module._pending)
        self.assertEqual(len(self.module.role_windows('TASKBAR')), 2)

    def test_close_never_touches_normal_windows(self):
        self.module.open_for_displays(self.context)
        self.windows.extend((Window('STARTMENU'), Window('TASK_CHOOSER')))
        self.module.close()
        self.assertEqual(len(self.windows), 1)
        self.assertEqual(self.windows[0].blui_shell_role, 'NORMAL')
        self.assertEqual(len(self.closed), 4)

    def test_normal_window_cannot_be_closed_by_role_helper(self):
        self.assertFalse(self.module.close_window(self.windows[0]))
        self.assertEqual(self.closed, [])

    def test_normal_window_cannot_be_repurposed_as_menu(self):
        with self.assertRaises(ValueError):
            self.module.place_menu(self.windows[0], self.windows[0], 500, 600)
        self.place.assert_not_called()

    def test_menu_targets_click_origin_monitor(self):
        bars = self.module.open_for_displays(self.context)
        source = next(window for window in bars if self.module.device(window) == 'LEFT')
        menu = Window('STARTMENU')
        self.windows.append(menu)
        self.module.place_menu(menu, source, 500, 600)
        self.assertEqual(self.place.call_args.kwargs['preferred'], 'LEFT')
        rect = self.place.call_args.args[1]
        self.assertTrue(-1920 <= rect[0] < rect[2] <= 0)
        self.assertEqual(self.module.device(menu), 'LEFT')

    def test_first_files_menu_waits_for_monitor_snapshot_without_blocking(self):
        self.snapshot = {'coordinate_space': 'physical', 'monitors': []}
        source = self.windows[0]
        menu = Window('STARTMENU')
        self.windows.append(menu)
        self.assertFalse(self.module.place_menu(menu, source, 500, 600))
        self.place.assert_not_called()
        self.assertEqual(len(self.module._pending_menus), 1)
        self.assertTrue(self.module.needs_service())
        self.snapshot = {'coordinate_space': 'physical', 'monitors': [display('MAIN', 0, True)]}
        self.module.tick(self.snapshot)
        self.place.assert_called_once()
        self.assertEqual(self.module._pending_menus, {})

    def test_closed_pending_menu_cannot_place_recycled_rna_window(self):
        self.snapshot = {'coordinate_space': 'physical', 'monitors': []}
        menu = Window('STARTMENU')
        self.windows.append(menu)
        self.module.place_menu(menu, self.windows[0], 500, 600)
        self.module.close_window(menu)
        self.snapshot = {'coordinate_space': 'physical', 'monitors': [display('MAIN', 0, True)]}
        self.module.tick(self.snapshot)
        self.place.assert_not_called()
        self.assertEqual(self.module._pending_menus, {})

    def test_layout_changes_do_not_create_or_close_windows(self):
        self.module.open_for_displays(self.context)
        self.module.set_alignment('LEFT')
        self.assertEqual(self.module.alignment(), 'LEFT')
        self.module.set_alignment('CENTER')
        self.assertEqual(self.module.alignment(), 'CENTER')
        with self.assertRaises(ValueError):
            self.module.set_alignment('UNKNOWN')
        self.assertEqual(len(self.created), 2)
        self.assertEqual(self.closed, [])

    def test_custom_ui_scale_combines_with_monitor_dpi_once(self):
        self.context.preferences.view.ui_scale = 2.0
        self.assertEqual(self.module.bar_rect(display('RIGHT', 0, True, 144)),
                         [0, 872, 1920, 1040])

    def test_custom_ui_scale_change_resizes_existing_bars(self):
        original = self.module.open_for_displays(self.context)
        self.place.reset_mock()
        self.context.preferences.view.ui_scale = 1.5
        self.module.tick(self.snapshot)
        self.assertEqual(self.created, original)
        self.assertEqual(self.place.call_count, 2)
        self.assertEqual(self.place.call_args.args[1], [0, 914, 1920, 1040])


if __name__ == '__main__':
    unittest.main(verbosity=2)
