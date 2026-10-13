# SPDX-License-Identifier: GPL-2.0-or-later
"""Taskbar safety tests. Never enumerate/hide/show a real Windows taskbar."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import taskbar_native as native
from blui_desktop import taskbar_state as state
from blui_desktop import window_placement as placement


def row(handle='123', *, visible=True, pid=300, thread=400, started='10000000',
        name='Shell_TrayWnd'):
    return {'handle': handle, 'pid': pid, 'thread_id': thread, 'process_started': started,
            'window_class': name, 'visible': visible}


class FakeBars:
    def __init__(self, rows):
        self.rows = {r['handle']: copy.deepcopy(r) for r in rows}
        self.calls = []
        self.failed = False

    def enumerate(self):
        return copy.deepcopy(list(self.rows.values()))

    def matches(self, row):
        current = self.rows.get(row['handle'])
        return current is not None and native.identity_key(current) == native.identity_key(row)

    def set_visible(self, row, value):
        if not self.matches(row):
            return False
        self.calls.append((row['handle'], value))
        if not self.failed:
            self.rows[row['handle']]['visible'] = value
        return True

    def visible(self, row):
        return self.matches(row) and self.rows[row['handle']]['visible']


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='blui-taskbar-test-')
        self.addCleanup(self.temp.cleanup)
        self.journal = state.Journal(self.temp.name)

    def guard(self, rows):
        bars = FakeBars(rows)
        return state.Guard(bars, self.journal), bars

    def test_default_does_not_hide(self):
        guard, bars = self.guard([row()])
        self.assertFalse(guard.enabled)
        self.assertTrue(guard.restore())
        self.assertEqual(bars.calls, [])

    def test_hide_main_and_secondary_restore_only_originally_visible(self):
        guard, bars = self.guard([row(), row('124', name='Shell_SecondaryTrayWnd'),
                                 row('125', visible=False)])
        guard.hide()
        self.assertEqual(guard.status()['hidden_count'], 2)
        self.assertEqual(len(self.journal.read()), 2)
        guard.restore()
        self.assertTrue(bars.rows['123']['visible'])
        self.assertTrue(bars.rows['124']['visible'])
        self.assertFalse(bars.rows['125']['visible'])
        self.assertNotIn(('125', True), bars.calls)

    def test_journal_written_before_hide(self):
        guard, bars = self.guard([row()])
        with patch.object(self.journal, 'write', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                guard.hide()
        self.assertEqual(bars.calls, [])
        self.assertTrue(bars.rows['123']['visible'])
        # A retry must persist again; a failed write cannot become implicit proof
        # of durability merely because the in-memory identity list is unchanged.
        guard.refresh()
        self.assertEqual(len(self.journal.read()), 1)
        self.assertFalse(bars.rows['123']['visible'])

    def test_steady_state_hide_does_not_rewrite_disk(self):
        guard, _bars = self.guard([row()])
        guard.hide()
        with patch.object(self.journal, 'write', wraps=self.journal.write) as writer:
            for _ in range(10):
                guard.refresh()
            writer.assert_not_called()

    def test_crashed_guard_is_recoverable(self):
        guard, bars = self.guard([row()])
        guard.hide()
        recovered = state.Guard(bars, self.journal)
        self.assertTrue(recovered.restore())
        self.assertTrue(bars.rows['123']['visible'])
        self.assertEqual(self.journal.read(), [])

    def test_recycled_identity_is_never_shown(self):
        for key, changed in (('pid', 301), ('thread_id', 401),
                             ('process_started', '10000001'), ('window_class', 'NotATaskbar')):
            guard, bars = self.guard([row()])
            guard.hide()
            bars.rows['123'][key] = changed
            bars.calls.clear()
            self.assertTrue(guard.restore())
            self.assertEqual(bars.calls, [])

    def test_explorer_restart_records_new_bars_before_hide(self):
        guard, bars = self.guard([row()])
        guard.hide()
        bars.rows = {'124': row('124', pid=302, started='10000009')}
        guard.refresh()
        self.assertEqual([r['handle'] for r in self.journal.read()], ['124'])
        self.assertFalse(bars.rows['124']['visible'])
        guard.restore()
        self.assertTrue(bars.rows['124']['visible'])

    def test_disconnected_screen_is_not_restored_to_a_reused_handle(self):
        guard, bars = self.guard([row(), row('124', name='Shell_SecondaryTrayWnd')])
        guard.hide()
        del bars.rows['124']
        guard.restore()
        self.assertEqual(self.journal.read(), [])

    def test_failed_restore_keeps_journal(self):
        guard, bars = self.guard([row()])
        guard.hide()
        bars.failed = True
        self.assertFalse(guard.restore())
        self.assertEqual(len(self.journal.read()), 1)
        bars.failed = False
        self.assertTrue(guard.refresh())
        self.assertEqual(self.journal.read(), [])

    def test_bad_and_duplicate_identity_rejected(self):
        for value in (row(visible=False), row(pid=True), row(started=''), row(name='Other'),
                      row(handle='0'), row(name=[])):
            with self.assertRaises(ValueError):
                native.validate_record(value)
        with patch('builtins.open', unittest.mock.mock_open(
                read_data=b'{"version":1,"bars":[' +
                __import__('json').dumps(row()).encode() + b',' +
                __import__('json').dumps(row()).encode() + b']}')):
            with self.assertRaises(ValueError):
                self.journal.read()

    def test_recovery_journal_is_utf8_no_bom(self):
        self.journal.write([row()])
        with open(self.journal.path, 'rb') as stream:
            self.assertFalse(stream.read().startswith(b'\xef\xbb\xbf'))

    def test_guardian_replays_journal_after_helper_crash(self):
        from blui_desktop import taskbar_recovery
        guard, bars = self.guard([row()])
        guard.hide()
        owner, helper, lock = unittest.mock.Mock(), unittest.mock.Mock(), unittest.mock.Mock()
        owner.alive.return_value = True
        helper.alive.return_value = False
        with (patch.object(taskbar_recovery, 'OwnerProcess', side_effect=[owner, helper]),
              patch.object(taskbar_recovery, 'SessionLock', return_value=lock),
              patch.object(taskbar_recovery, 'WindowsBars', return_value=bars),
              patch.object(taskbar_recovery.sys, 'stdout', unittest.mock.Mock())):
            taskbar_recovery.run(self.temp.name, 10, '20', 30, '40')
        self.assertTrue(bars.rows['123']['visible'])
        self.assertEqual(self.journal.read(), [])
        owner.close.assert_called_once()
        helper.close.assert_called_once()
        lock.close.assert_called_once()

    def test_guardian_does_not_compete_with_new_guard(self):
        from blui_desktop import taskbar_recovery
        owner, helper = unittest.mock.Mock(), unittest.mock.Mock()
        owner.alive.return_value = True
        helper.alive.return_value = False
        with (patch.object(taskbar_recovery, 'OwnerProcess', side_effect=[owner, helper]),
              patch.object(taskbar_recovery, 'SessionLock', side_effect=RuntimeError('guard active')),
              patch.object(taskbar_recovery, 'WindowsBars') as backend,
              patch.object(taskbar_recovery.sys, 'stdout', unittest.mock.Mock())):
            taskbar_recovery.run(self.temp.name, 10, '20', 30, '40')
        backend.assert_not_called()


class PlacementTests(unittest.TestCase):
    displays = {'coordinate_space': 'physical', 'monitors': [{
        'device': 'DISPLAY1', 'rect': [-1920, 0, 0, 1080],
        'work': [-1920, 0, 0, 1040], 'dpi': [144, 144], 'primary': True}]}

    def test_invalid_handle_rejected(self):
        for handle in (True, 0, '0', '', '-1', 'abc', 1 << 64):
            with self.assertRaises(ValueError):
                placement._handle(handle)

    def test_offscreen_and_wrong_monitor_rejected_before_native_action(self):
        with patch.object(placement, '_api') as api:
            with self.assertRaises(ValueError):
                placement.place('123', [100, 100, 500, 500], self.displays)
            with self.assertRaises(ValueError):
                placement.place('123', [-1900, 0, -1600, 300], self.displays, preferred='gone')
            api.assert_not_called()

    def test_foreign_or_stale_identity_rejected(self):
        for value in (None, (os.getpid() + 1, 1, '10', 'GHOST_WindowClass'),
                      (os.getpid(), 1, '', 'GHOST_WindowClass'),
                      (os.getpid(), 1, '10', 'Other')):
            with patch.object(placement.native_windows, '_identity', return_value=value):
                with self.assertRaises(RuntimeError):
                    placement._own(object(), 123)

    def test_placement_flags_are_async_no_focus_no_z_order(self):
        api = unittest.mock.Mock()
        api.SetWindowPos.return_value = True
        with patch.object(placement, '_api', return_value=api), patch.object(
                placement, '_own', return_value=(os.getpid(), 1, '10', 'GHOST_WindowClass')):
            placement.place('123', [-1900, 0, -1600, 300], self.displays)
        self.assertEqual(api.SetWindowPos.call_args.args, (123, None, -1900, 0, 300, 300, 0x4214))

    def test_partly_visible_window_is_not_moved(self):
        with (patch.object(placement, 'bounds', return_value={'rect': [-2000, 0, -1800, 300]}),
              patch.object(placement, 'place') as move):
            self.assertFalse(placement.recover('123', self.displays))
            move.assert_not_called()


@unittest.skipUnless(os.name == 'nt', 'Win32 helper lifecycle test')
class HelperLifecycleTests(unittest.TestCase):
    def test_read_only_event_helper_starts_and_stops_without_taskbar_mutation(self):
        from blui_desktop import taskbar
        with tempfile.TemporaryDirectory(prefix='blui-taskbar-readonly-') as directory:
            controller = taskbar.Controller(directory)
            deadline = time.monotonic() + 10
            try:
                while time.monotonic() < deadline:
                    result = controller.tick()
                    if result['events_available'] or result['error']:
                        break
                    time.sleep(.05)
                self.assertEqual(result['error'], '')
                self.assertTrue(result['events_available'])
                self.assertFalse(result['enabled'])
                self.assertEqual(result['hidden_count'], 0)
                self.assertGreater(result['tasks_revision'], 0)
            finally:
                controller.close()
                controller._thread.join(timeout=6)
            self.assertFalse(controller._thread.is_alive())
            self.assertIsNotNone(controller.process.poll())
            self.assertEqual(state.Journal(directory).read(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
