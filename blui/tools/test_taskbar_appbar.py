# SPDX-License-Identifier: GPL-2.0-or-later
"""Mock-only AppBar tests: no real SHAppBarMessage or work-area writes."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import taskbar_appbar as appbar


def display(device='DISPLAY1', x=-1920, dpi=144):
    return {'device': device, 'rect': [x, -300, x + 1920, 780],
            'work': [x, -300, x + 1920, 740], 'dpi': [dpi, dpi], 'primary': device == 'DISPLAY1'}


class AppBarTests(unittest.TestCase):
    def setUp(self):
        self.user, self.shell = mock.Mock(), mock.Mock()
        self.windows = {'DISPLAY1': SimpleNamespace(blui_shell_role='TASKBAR', blui_native_handle='99',
                                                   as_pointer=lambda: 1)}
        self.snapshot = {'coordinate_space': 'physical', 'monitors': [display()]}
        self.owned = (999, 22, '44444', 'GHOST_WindowClass')
        self.properties = {}
        self.user.GetPropW.side_effect = lambda handle, name: self.properties.get((handle, name), 0)
        def set_property(handle, name, value):
            self.properties[(handle, name)] = value
            return True
        self.user.SetPropW.side_effect = set_property
        self.user.RemovePropW.side_effect = lambda handle, name: self.properties.pop((handle, name), 0)
        self.user.GetWindowLongPtrW.side_effect = lambda _handle, index: 0x08000080 if index == -20 else 0x80000000
        self.system_reserve = 40
        self.set_shift = 0
        self.messages = []
        def message(number, pointer):
            data = pointer._obj
            self.messages.append((number, data.window, data.size, data.callback,
                                  [data.rect.left, data.rect.top, data.rect.right, data.rect.bottom]))
            if number == appbar.ABM_QUERYPOS:
                data.rect.bottom -= self.system_reserve
            if number == appbar.ABM_SETPOS:
                data.rect.top -= self.set_shift
                data.rect.bottom -= self.set_shift
            return 1
        self.shell.SHAppBarMessage.side_effect = message
        for patcher in (
            mock.patch.object(appbar, '_api', return_value=self.shell),
            mock.patch.object(appbar.native_windows, '_api', return_value=self.user),
            mock.patch.object(appbar.window_placement, '_own', return_value=self.owned),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.controller = appbar.AppBarController()
        self.addCleanup(self.controller.close)

    def reconcile(self, height=56):
        return self.controller.reconcile(self.windows, self.snapshot, height)

    def test_bottom_edge_honors_original_taskbar_negative_monitor_dpi(self):
        self.assertEqual(self.reconcile(), {'DISPLAY1': [-1920, 656, 0, 740]})
        self.assertEqual([entry[0] for entry in self.messages], [0, 2, 3])
        self.assertTrue(all(entry[1] == 99 for entry in self.messages))
        self.assertEqual(self.messages[0][3], appbar.CALLBACK_MESSAGE)
        self.assertEqual(self.snapshot['monitors'][0]['work'], [-1920, -300, 0, 740])

    def test_unchanged_geometry_and_notifications_skip_all_shell_ipc(self):
        self.reconcile()
        self.reconcile()
        self.assertEqual([entry[0] for entry in self.messages], [0, 2, 3])
        result = self.controller.snapshot()
        result['DISPLAY1'][0] = 999
        self.assertNotEqual(self.controller.snapshot()['DISPLAY1'][0], 999)

    def test_new_size_queries_monitor_not_self_reduced_workarea(self):
        self.reconcile()
        self.snapshot['monitors'][0]['work'][3] = 656
        self.assertEqual(self.reconcile(64), {'DISPLAY1': [-1920, 644, 0, 740]})

    def test_system_reclaim_work_change_requeries_without_double_height(self):
        self.reconcile()
        self.system_reserve = 0  # Explorer auto-hide releases only its reservation.
        self.snapshot['monitors'][0]['work'][3] = 780
        self.assertEqual(self.reconcile(), {'DISPLAY1': [-1920, 696, 0, 780]})
        # Our SETPOS changes work area once: one query, no second deduction/SETPOS.
        self.snapshot['monitors'][0]['work'][3] = 696
        self.reconcile()
        self.reconcile()
        self.assertEqual([entry[0] for entry in self.messages], [0, 2, 3, 2, 3, 2])

    def test_explicit_handoff_invalidation_only_requeries_once(self):
        self.reconcile()
        self.controller.invalidate()
        self.assertEqual([entry[0] for entry in self.messages], [0, 2, 3])
        self.reconcile()
        self.reconcile()
        self.assertEqual([entry[0] for entry in self.messages], [0, 2, 3, 2])

    def test_shell_final_adjustment_is_used(self):
        self.set_shift = 10
        self.assertEqual(self.reconcile(), {'DISPLAY1': [-1920, 646, 0, 730]})

    def test_two_displays_independent_and_disconnect_clears_reservation(self):
        self.snapshot['monitors'].append(display('DISPLAY2', 0, 96))
        self.windows['DISPLAY2'] = SimpleNamespace(blui_shell_role='TASKBAR', blui_native_handle='100',
                                                  as_pointer=lambda: 2)
        self.assertEqual(self.reconcile()['DISPLAY2'], [0, 684, 1920, 740])
        self.snapshot['monitors'].pop()
        self.reconcile()
        self.assertEqual([row[1] for row in self.messages if row[0] == 1], [100])

    def test_only_registered_own_window_close_unregisters_exact_once(self):
        self.reconcile()
        self.controller.close_window(self.windows['DISPLAY1'])
        self.controller.close()
        self.assertEqual([row[0] for row in self.messages], [0, 2, 3, 1])
        self.assertEqual(self.controller.snapshot(), {})
        self.assertNotIn(self.controller, appbar._controllers)

    def test_reused_hwnd_is_never_removed_from_new_owner(self):
        self.reconcile()
        with mock.patch.object(appbar.window_placement, '_own', return_value=(888, 22, '99999', 'GHOST_WindowClass')):
            self.controller.close()
        self.assertNotIn(1, [row[0] for row in self.messages])
        self.assertEqual(self.controller.snapshot(), {})

    def test_invalid_role_foreign_identity_or_child_never_registers(self):
        for invalid in ('NORMAL', 'STARTMENU', 'TASK_CHOOSER'):
            self.windows['DISPLAY1'].blui_shell_role = invalid
            with self.assertRaises(ValueError):
                self.reconcile()
        self.windows['DISPLAY1'].blui_shell_role = 'TASKBAR'
        with mock.patch.object(appbar.window_placement, '_own', side_effect=RuntimeError('foreign')):
            with self.assertRaises(RuntimeError):
                self.reconcile()
        self.user.GetWindowLongPtrW.side_effect = lambda _handle, index: 0x40000000 if index == -16 else 0x08000080
        with self.assertRaises(RuntimeError):
            self.reconcile()
        self.shell.SHAppBarMessage.assert_not_called()

    def test_identity_race_before_setpos_does_not_modify_reused_window(self):
        send = self.shell.SHAppBarMessage.side_effect
        changed = [False]
        def change_on_query(number, pointer):
            result = send(number, pointer)
            if number == appbar.ABM_QUERYPOS:
                changed[0] = True
            return result
        self.shell.SHAppBarMessage.side_effect = change_on_query
        with mock.patch.object(appbar.window_placement, '_own', side_effect=lambda *_args:
                               (888, 22, '99999', 'GHOST_WindowClass') if changed[0] else self.owned):
            with self.assertRaises(RuntimeError):
                self.reconcile()
        self.assertEqual([row[0] for row in self.messages], [0, 2])
        self.assertEqual(self.controller.snapshot(), {})

    def test_failed_register_leaves_no_retained_reservation(self):
        self.shell.SHAppBarMessage.side_effect = None
        self.shell.SHAppBarMessage.return_value = 0
        with self.assertRaises(OSError):
            self.reconcile()
        self.assertEqual(self.controller.snapshot(), {})
        self.assertEqual(self.shell.SHAppBarMessage.call_count, 1)

    def test_offmonitor_approved_rect_removes_owned_reservation(self):
        self.set_shift = 2000
        with self.assertRaises(RuntimeError):
            self.reconcile()
        self.assertEqual([row[0] for row in self.messages], [0, 2, 3, 1])
        self.assertEqual(self.controller.snapshot(), {})

    def test_invalid_height_duplicate_hwnd_and_empty_displays(self):
        for height in (True, float('nan'), 0, 1281):
            with self.assertRaises(ValueError):
                self.reconcile(height)
        self.snapshot['monitors'].append(display('DISPLAY2', 0, 96))
        self.windows['DISPLAY2'] = self.windows['DISPLAY1']
        with self.assertRaises(ValueError):
            self.reconcile()
        self.shell.SHAppBarMessage.assert_not_called()
        self.controller.reconcile({}, {'coordinate_space': 'physical', 'monitors': []}, 56)
        self.shell.SHAppBarMessage.assert_not_called()

    def test_position_changed_notifies_shell_only_for_own_registered_window(self):
        self.reconcile()
        self.assertTrue(self.controller.position_changed(self.windows['DISPLAY1']))
        self.assertEqual(self.messages[-1][0], 9)
        self.controller.close()
        self.assertFalse(self.controller.position_changed(self.windows['DISPLAY1']))

    def test_native_fullscreen_and_generation_flags_read_only_for_own_marker(self):
        self.reconcile()
        self.properties[(99, appbar.FULLSCREEN_PROPERTY)] = 1
        self.properties[(99, appbar.GENERATION_PROPERTY)] = 4
        self.assertTrue(appbar.is_fullscreen(self.windows['DISPLAY1']))
        self.assertEqual(appbar.notification_state(self.windows['DISPLAY1'])['generation'], 4)
        self.controller.close()
        self.assertFalse(appbar.is_fullscreen(self.windows['DISPLAY1']))

    def test_native_position_generation_invalidates_once_without_setpos_loop(self):
        self.reconcile()
        self.properties[(99, appbar.GENERATION_PROPERTY)] += 1
        self.reconcile()
        self.reconcile()
        self.assertEqual([entry[0] for entry in self.messages], [0, 2, 3, 2])

    def test_geometry_dpi_and_fullscreen_changes_each_requery_once(self):
        self.reconcile()
        self.snapshot['monitors'][0]['dpi'] = [96, 96]
        self.reconcile()
        self.properties[(99, appbar.FULLSCREEN_PROPERTY)] = 1
        self.reconcile()
        self.reconcile()
        self.assertEqual([entry[0] for entry in self.messages], [0, 2, 3, 2, 3, 2])

    def test_explorer_restart_reregisters_and_sets_same_geometry(self):
        self.reconcile()
        self.properties[(99, appbar.RESTART_PROPERTY)] += 1
        self.reconcile()
        self.assertEqual([entry[0] for entry in self.messages], [0, 2, 3, 0, 2, 3])

    def test_missing_same_process_registration_token_is_not_unregistered(self):
        self.reconcile()
        self.properties[(99, appbar.TOKEN_PROPERTY)] += 1
        self.controller.close()
        self.assertNotIn(1, [entry[0] for entry in self.messages])

    def test_native_marker_failure_does_not_register(self):
        self.user.SetPropW.side_effect = None
        self.user.SetPropW.return_value = False
        with self.assertRaises(OSError):
            self.reconcile()
        self.shell.SHAppBarMessage.assert_not_called()

    def test_another_controller_marker_is_not_overwritten_or_cleared(self):
        self.properties[(99, appbar.OWNER_PROPERTY)] = appbar.os.getpid()
        self.properties[(99, appbar.TOKEN_PROPERTY)] = 12345
        with self.assertRaises(RuntimeError):
            self.reconcile()
        self.assertEqual(self.properties[(99, appbar.TOKEN_PROPERTY)], 12345)
        self.user.SetPropW.assert_not_called()
        self.user.RemovePropW.assert_not_called()
        self.shell.SHAppBarMessage.assert_not_called()


if __name__ == '__main__':
    unittest.main()
