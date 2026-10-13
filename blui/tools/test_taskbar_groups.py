# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure task grouping/launch guard tests. Never launch, move, hide or close real windows."""
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import taskbar_groups as groups, native_windows as native


def task(handle='10', *, executable='C:\\Program Files\\App\\App.exe', app_id='', monitor='DISPLAY1', **extra):
    return {'handle': handle, 'pid': 100, 'thread_id': 101, 'process_started': '10000000',
            'window_class': 'AppWindow', 'title': 'Document ' + handle,
            'actionable': True, 'active': False, 'minimized': False,
            'executable': executable, 'app_id': app_id, 'monitor': monitor, **extra}


class GroupTests(unittest.TestCase):
    def test_hidden_system_bar_uses_physical_edge_without_changing_snapshot(self):
        display = {'rect': [-1920, 0, 0, 1080], 'work': [-1920, 0, 0, 1040], 'dpi': [96, 96]}
        self.assertEqual(groups.bar_rect(display, system_hidden=True), [-1920, 1024, 0, 1080])
        self.assertEqual(groups.bar_rect(display), [-1920, 984, 0, 1040])
        self.assertEqual(display['work'], [-1920, 0, 0, 1040])
    def test_same_executable_has_one_icon_many_windows(self):
        result = groups.groups([task(), task('11', active=True)])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['tasks']), 2)
        self.assertTrue(result[0]['active'])
        self.assertEqual(result[0]['title'], 'App')

    def test_windows_paths_case_and_slashes_normalize(self):
        self.assertEqual(groups.identity_key(task()), groups.identity_key(
            task('11', executable='c:/program files/app/app.exe')))

    def test_distinct_executable_directories_do_not_merge(self):
        self.assertEqual(len(groups.groups([task(), task('11', executable='D:\\Other\\App.exe')])), 2)

    def test_packaged_identity_is_not_broker_name(self):
        broker = 'C:\\Windows\\System32\\ApplicationFrameHost.exe'
        rows = [task(executable=broker, app_id='Publisher.A!App'),
                task('11', executable=broker, app_id='Publisher.B!App')]
        self.assertEqual(len(groups.groups(rows)), 2)
        self.assertFalse(groups.can_launch(rows[0]))

    def test_unidentified_broker_windows_do_not_merge(self):
        broker = 'C:\\Windows\\System32\\ApplicationFrameHost.exe'
        self.assertEqual(len(groups.groups([task(executable=broker), task('11', executable=broker)])), 2)

    def test_inaccessible_metadata_never_groups_by_window_title(self):
        first, second = task(executable=''), task('11', executable='', title='Document 10', actionable=False)
        self.assertEqual(len(groups.groups([first, second])), 2)
        self.assertFalse(groups.can_launch(second))

    def test_monitor_filter_and_shell_handles(self):
        rows = [task(), task('11', monitor='DISPLAY2'), task('12', monitor='')]
        result = groups.groups(rows, monitor='DISPLAY1', all_monitors=False, excluded=('10',))
        self.assertEqual([row['handle'] for row in result[0]['tasks']], ['12'])
        self.assertEqual(len(groups.groups(rows, excluded=('10',))[0]['tasks']), 2)

    def test_group_snapshot_does_not_mutate_task_cache(self):
        original = task()
        grouped = groups.groups([original])
        grouped[0]['tasks'][0]['active'] = True
        self.assertFalse(original['active'])

    def test_launch_requires_verified_absolute_executable(self):
        for value in ('app.exe', '/app.exe', '', 'C:\\apps\\readme.txt', 'C:\\app.exe\x00'):
            self.assertFalse(groups.can_launch(task(executable=value)))
        self.assertTrue(groups.can_launch(task()))
        self.assertFalse(groups.can_launch(task(actionable=False)))

    def test_bar_negative_monitor_origin_and_dpi(self):
        display = {'work': [-2560, -300, -640, 780], 'dpi': [144, 144]}
        self.assertEqual(groups.bar_rect(display), [-2560, 696, -640, 780])

    def test_menu_is_clamped_to_source_display(self):
        display = {'work': [-1920, 0, 0, 1040], 'dpi': [96, 96]}
        self.assertEqual(groups.menu_rect(display, [-50, 992], 500, 600), [-500, 392, 0, 992])

    def test_menu_on_small_monitor_never_offscreen(self):
        display = {'work': [0, 0, 320, 240], 'dpi': [192, 192]}
        self.assertEqual(groups.menu_rect(display, [160, 192], 500, 600), [0, 0, 320, 240])


class ToggleTests(unittest.TestCase):
    def test_click_uses_fresh_foreground_instead_of_cached_active_flag(self):
        for foreground, iconic, expected in ((10, False, 6), (11, False, 5), (10, True, 9)):
            api = mock.Mock()
            api.GetForegroundWindow.return_value = foreground
            api.IsIconic.return_value = iconic
            api.SetForegroundWindow.return_value = True
            with (mock.patch.object(native, '_api', return_value=api),
                  mock.patch.object(native, '_identity', return_value=(100, 101, '10000000', 'AppWindow'))):
                self.assertTrue(native.act('10', 100, identity=(101, '10000000', 'AppWindow'), toggle=True))
                api.ShowWindowAsync.assert_called_once_with(10, expected)

    def test_stale_identity_is_rejected_before_toggle_queries(self):
        api = mock.Mock()
        with (mock.patch.object(native, '_api', return_value=api),
              mock.patch.object(native, '_identity', return_value=None)):
            with self.assertRaises(RuntimeError):
                native.act('10', 100, identity=(101, '10000000', 'AppWindow'), toggle=True)
            api.GetForegroundWindow.assert_not_called()
            api.ShowWindowAsync.assert_not_called()


class LaunchGuardTests(unittest.TestCase):
    def setUp(self):
        self.row = task()
        self.identity = (100, 101, '10000000', 'AppWindow')
        self.api = mock.Mock()
        self.api.GetWindowLongPtrW.return_value = 0

    def launch(self, *, identities=None, metadata=None):
        with (mock.patch.object(native, '_api', return_value=self.api),
              mock.patch.object(native, '_identity', side_effect=identities or [self.identity, self.identity]),
              mock.patch.object(native, '_metadata', return_value=metadata or {
                  'executable': self.row['executable'], 'app_id': ''}),
              mock.patch.object(native.subprocess, 'Popen') as start):
            value = native.launch(self.row)
        return value, start

    def test_valid_launch_uses_one_exact_path_argument_without_shell(self):
        value, start = self.launch()
        self.assertTrue(value)
        start.assert_called_once_with([self.row['executable']], close_fds=True)

    def test_stale_pid_thread_start_or_class_never_launches(self):
        for identity in ((101, 101, '10000000', 'AppWindow'), (100, 102, '10000000', 'AppWindow'),
                         (100, 101, '10000001', 'AppWindow'), (100, 101, '10000000', 'Other')):
            with (mock.patch.object(native, '_api', return_value=self.api),
                  mock.patch.object(native, '_identity', return_value=identity),
                  mock.patch.object(native.subprocess, 'Popen') as start):
                with self.assertRaises(RuntimeError):
                    native.launch(self.row)
                start.assert_not_called()

    def test_changed_executable_never_launches(self):
        with self.assertRaises(RuntimeError):
            self.launch(metadata={'executable': 'D:\\different.exe', 'app_id': ''})

    def test_window_changed_after_executable_query_never_launches(self):
        with self.assertRaises(RuntimeError):
            self.launch(identities=[self.identity, None])

    def test_own_auxiliary_tool_window_is_not_new_instance_target(self):
        self.api.GetWindowLongPtrW.return_value = 0x80
        with self.assertRaises(RuntimeError):
            self.launch()

    def test_unactionable_and_packaged_tasks_rejected_before_api(self):
        with mock.patch.object(native, '_api') as api:
            for value in (task(actionable=False), task(app_id='Package!App'), task(executable='App.exe'),
                          task(pid=True), task(handle='0'), task(thread_id=False)):
                with self.assertRaises(ValueError):
                    native.launch(value)
            api.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
