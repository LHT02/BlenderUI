# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure/mock tests: never change the desktop, run a helper or mutate native windows."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import taskbar_native as native, taskbar_state as visibility
from blui_desktop import taskbar_reservation as reservation


def bar(handle='123', name='Shell_TrayWnd', started='10000', visible=True):
    return {'handle': handle, 'pid': 30, 'thread_id': 40, 'process_started': started,
            'window_class': name, 'visible': visible}


class MemoryJournal:
    def __init__(self):
        self.entry = None
        self.writes = []
        self.failed = False

    def read(self):
        return copy.deepcopy(self.entry)

    def write(self, entry):
        if self.failed:
            raise OSError('disk unavailable')
        self.entry = copy.deepcopy(entry)
        self.writes.append(copy.deepcopy(entry))


class FakeBars:
    def __init__(self, state=0):
        self.rows = {'123': bar(), '124': bar('124', 'Shell_SecondaryTrayWnd')}
        self.state = state
        self.available = True
        self.delayed = False
        self.fail = False
        self.calls = []
        self.before_state = None

    def enumerate(self):
        return [dict(row) for row in self.rows.values()] if self.available else []

    def primary(self):
        return next((row for row in self.enumerate() if row['window_class'] == 'Shell_TrayWnd'), None)

    def matches(self, row):
        fresh = self.rows.get(row['handle'])
        return self.available and fresh is not None and native.identity_key(fresh) == native.identity_key(row)

    def reservation_state(self, row):
        return self.state if self.matches(row) else None

    def set_reservation_state(self, row, state):
        if not self.matches(row) or self.fail:
            return False
        if self.before_state:
            self.before_state(row, state)
        self.calls.append(('state', row['handle'], state))
        if not self.delayed:
            self.state = state
        return True

    def set_visible(self, row, visible):
        if not self.matches(row):
            return False
        self.calls.append(('visible', row['handle'], visible))
        self.rows[row['handle']]['visible'] = visible
        return True

    def visible(self, row):
        return bool(self.matches(row) and self.rows[row['handle']]['visible'])


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.bars, self.journal = FakeBars(), MemoryJournal()
        self.now = 0.0
        self.controller = reservation.ReservationController(self.bars, self.journal, lambda: self.now)

    def test_all_original_bits_restored_and_existing_autohide_never_written(self):
        for original in range(4):
            with self.subTest(original=original):
                bars, journal = FakeBars(original), MemoryJournal()
                controller = reservation.ReservationController(bars, journal)
                self.assertTrue(controller.ensure())
                self.assertEqual(bars.state, original | 1)
                self.assertTrue(controller.restore())
                self.assertEqual(bars.state, original)
                self.assertEqual(len(bars.calls), 0 if original & 1 else 2)
                self.assertIsNone(journal.entry)

    def test_restore_preserves_later_other_bit_change(self):
        self.controller.ensure()
        self.bars.state = 3  # Someone changed the other bit while we owned AUTOHIDE.
        self.assertTrue(self.controller.restore())
        self.assertEqual(self.bars.state, 2)

    def test_intent_is_durable_before_state_mutation(self):
        self.bars.before_state = lambda row, state: self.assertEqual(
            self.journal.entry['primary'], row)
        self.assertTrue(self.controller.ensure())

    def test_journal_failure_never_changes_state(self):
        self.journal.failed = True
        with self.assertRaises(OSError):
            self.controller.ensure()
        self.assertEqual(self.bars.calls, [])

    def test_steady_state_does_not_rewrite_or_force_state(self):
        self.controller.ensure()
        for _ in range(10):
            self.assertTrue(self.controller.ensure())
        self.assertEqual(len(self.journal.writes), 1)
        self.assertEqual(len(self.bars.calls), 1)

    def test_delayed_readback_never_hides_until_confirmed(self):
        self.bars.delayed = True
        self.assertIsNone(self.controller.ensure())
        self.now = 1.0
        self.assertIsNone(self.controller.ensure())
        self.assertEqual(len(self.bars.calls), 1)
        self.bars.state = 1
        self.assertTrue(self.controller.ensure())

    def test_timeout_relinquishes_without_repeated_forcing(self):
        self.bars.delayed = True
        self.controller.ensure()
        self.now = 3.0
        self.assertFalse(self.controller.ensure())
        self.assertEqual(len(self.bars.calls), 1)
        self.assertTrue(self.controller.restore())

    def test_external_autohide_change_not_overwritten(self):
        self.controller.ensure()
        self.now = 3.0
        self.bars.state = 2
        self.assertFalse(self.controller.ensure())
        self.assertIn('externally', self.controller.error)
        self.assertTrue(self.controller.restore())
        self.assertEqual(self.bars.state, 2)
        self.assertEqual(len(self.bars.calls), 1)

    def test_no_primary_waits_without_mutation(self):
        self.bars.available = False
        self.assertIsNone(self.controller.ensure())
        self.assertEqual(self.bars.calls, [])
        self.assertIsNone(self.journal.entry)

    def test_explorer_epoch_transfer_durable_before_new_write(self):
        self.controller.ensure()
        self.bars.rows = {'223': bar('223', started='20000')}
        self.bars.state = 2
        self.bars.before_state = lambda row, state: self.assertEqual(
            self.journal.entry['primary']['handle'], '223')
        self.assertTrue(self.controller.ensure())
        self.assertEqual(self.journal.entry['original_state'], 0)
        self.assertEqual(self.bars.state, 3)
        self.assertTrue(self.controller.restore())
        self.assertEqual(self.bars.state, 2)

    def test_crash_recovery_rebinds_current_explorer_never_saved_handle(self):
        self.controller.ensure()
        self.bars.rows = {'223': bar('223', started='20000')}
        self.bars.calls.clear()
        recovered = reservation.ReservationController(self.bars, self.journal)
        self.assertTrue(recovered.restore())
        self.assertEqual(self.bars.calls, [('state', '223', 0)])

    def test_explorer_absent_keeps_restoration_intent(self):
        self.controller.ensure()
        self.bars.available = False
        self.assertFalse(self.controller.restore())
        self.assertIsNotNone(self.journal.entry)
        self.assertTrue(self.controller.pending)
        self.bars.available = True
        self.assertTrue(self.controller.restore())

    def test_unconfirmed_restore_keeps_journal_for_guardian(self):
        self.controller.ensure()
        self.bars.delayed = True
        self.assertFalse(self.controller.restore())
        self.assertIsNotNone(self.journal.entry)
        self.now = 3.0
        self.assertFalse(self.controller.restore())
        self.bars.delayed = False
        self.assertTrue(self.controller.restore())

    def test_restore_original_autohide_does_not_require_shell_available(self):
        self.bars.state = 1
        self.controller.ensure()
        self.bars.available = False
        self.assertTrue(self.controller.restore())
        self.assertEqual(self.bars.calls, [])


class JournalAndGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='blui-reservation-pure-')
        self.addCleanup(self.temp.cleanup)
        self.resjournal = reservation.ReservationJournal(self.temp.name)
        self.visible_journal = visibility.Journal(self.temp.name)
        self.bars = FakeBars()
        self.now = 0.0
        self.controller = reservation.ReservationController(self.bars, self.resjournal, lambda: self.now)
        self.guard = visibility.Guard(self.bars, self.visible_journal, self.controller)

    def test_utf8_no_bom_and_roundtrip(self):
        self.controller.ensure()
        raw = Path(self.resjournal.path).read_bytes()
        self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(self.resjournal.read(), self.controller.entry)

    def test_bad_schema_secondary_duplicate_and_oversize_rejected(self):
        self.controller.ensure()
        valid = self.controller.entry
        for bad in ({}, dict(valid, changed=1), dict(valid, forced_state=0),
                    dict(valid, original_state=True), dict(valid, primary=bar(name='Shell_SecondaryTrayWnd'))):
            with self.assertRaises(ValueError):
                self.resjournal.write(bad)
        with patch('builtins.open', return_value=io.BytesIO(b' ' * (reservation.MAX_BYTES + 1))):
            with self.assertRaises(ValueError):
                self.resjournal.read()

    def test_visibility_intent_exists_before_autohide_changes_visible_state(self):
        def before_state(_row, _state):
            self.assertEqual(len(self.visible_journal.read()), 2)
            for row in self.bars.rows.values():
                row['visible'] = False  # Explorer can auto-hide in response to SETSTATE.
        self.bars.before_state = before_state
        self.assertTrue(self.guard.hide())
        self.bars.before_state = None
        self.assertTrue(self.guard.restore())
        self.assertTrue(all(row['visible'] for row in self.bars.rows.values()))

    def test_visibility_failed_save_precedes_all_state_writes(self):
        with patch.object(self.visible_journal, 'write', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.guard.hide()
        self.assertEqual(self.bars.calls, [])

    def test_external_change_stops_hiding_and_restores_only_our_bars(self):
        self.bars.rows['125'] = bar('125', 'Shell_SecondaryTrayWnd', visible=False)
        self.guard.hide()
        self.now, self.bars.state = 3.0, 0
        self.assertFalse(self.guard.refresh())
        self.assertFalse(self.guard.enabled)
        self.assertTrue(self.bars.rows['123']['visible'])
        self.assertTrue(self.bars.rows['124']['visible'])
        self.assertFalse(self.bars.rows['125']['visible'])
        self.assertIn('externally', self.guard.status()['error'])

    def test_empty_visibility_crash_gap_recovers_reservation(self):
        self.controller.ensure()  # Crash after SETSTATE but before first visibility write.
        fresh = reservation.ReservationController(self.bars, self.resjournal)
        guard = visibility.Guard(self.bars, self.visible_journal, fresh)
        self.assertTrue(guard.restore())
        self.assertEqual(self.bars.state, 0)
        self.assertIsNone(self.resjournal.read())

    def test_pending_reclaim_does_not_hide_windows(self):
        self.bars.delayed = True
        self.assertFalse(self.guard.hide())
        self.assertTrue(all(row['visible'] for row in self.bars.rows.values()))
        self.assertTrue(self.guard.status()['reservation_pending'])

    def test_visibility_restore_disk_failure_still_undoes_autohide(self):
        self.guard.hide()
        with patch.object(self.visible_journal, 'write', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.guard.restore()
        self.assertEqual(self.bars.state, 0)
        self.assertIsNone(self.resjournal.read())

    def test_second_guardian_recovers_even_when_visibility_journal_empty(self):
        from blui_desktop import taskbar_recovery
        self.controller.ensure()
        owner, helper, lock = Mock(), Mock(), Mock()
        owner.alive.return_value, helper.alive.return_value = True, False
        with (patch.object(taskbar_recovery, 'OwnerProcess', side_effect=[owner, helper]),
              patch.object(taskbar_recovery, 'SessionLock', return_value=lock),
              patch.object(taskbar_recovery, 'WindowsBars', return_value=self.bars),
              patch.object(taskbar_recovery.sys, 'stdout', Mock())):
            taskbar_recovery.run(self.temp.name, 10, '20', 30, '40')
        self.assertEqual(self.bars.state, 0)
        self.assertIsNone(self.resjournal.read())

    def test_second_guardian_retries_while_explorer_is_recreating(self):
        from blui_desktop import taskbar_recovery
        self.controller.ensure()
        self.bars.available = False
        owner, helper, lock = Mock(), Mock(), Mock()
        owner.alive.return_value, helper.alive.return_value = True, False
        sleeps = []
        def shell_reappears(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 6:
                self.bars.available = True
        with (patch.object(taskbar_recovery, 'OwnerProcess', side_effect=[owner, helper]),
              patch.object(taskbar_recovery, 'SessionLock', return_value=lock),
              patch.object(taskbar_recovery, 'WindowsBars', return_value=self.bars),
              patch.object(taskbar_recovery.sys, 'stdout', Mock()),
              patch.object(taskbar_recovery.time, 'sleep', side_effect=shell_reappears)):
            taskbar_recovery.run(self.temp.name, 10, '20', 30, '40')
        self.assertEqual(sleeps, [.25] * 6)
        self.assertEqual(self.bars.state, 0)
        self.assertIsNone(self.resjournal.read())


class NativeBoundaryTests(unittest.TestCase):
    def test_exact_stale_identity_never_calls_native_state_api(self):
        backend = object.__new__(native.WindowsBars)
        backend.shell = Mock()
        backend.matches = Mock(return_value=False)
        self.assertIsNone(backend.reservation_state(bar()))
        self.assertFalse(backend.set_reservation_state(bar(), 1))
        backend.shell.SHAppBarMessage.assert_not_called()

    def test_secondary_bar_never_controls_global_state(self):
        backend = object.__new__(native.WindowsBars)
        backend.shell, backend.matches = Mock(), Mock(return_value=True)
        self.assertFalse(backend.set_reservation_state(bar(name='Shell_SecondaryTrayWnd'), 1))
        backend.shell.SHAppBarMessage.assert_not_called()

    def test_identity_rechecked_immediately_before_write(self):
        backend = object.__new__(native.WindowsBars)
        backend.shell = Mock()
        backend.matches = Mock(side_effect=[True, True, False])
        self.assertFalse(backend.set_reservation_state(bar(), 1))
        backend.shell.SHAppBarMessage.assert_not_called()

    def test_state_zero_is_valid_and_postread_identity_required(self):
        backend = object.__new__(native.WindowsBars)
        backend.shell = Mock()
        backend.shell.SHAppBarMessage.return_value = 0
        backend.matches = Mock(return_value=True)
        self.assertEqual(backend.reservation_state(bar()), 0)
        backend.matches = Mock(side_effect=[True, True, False])
        self.assertIsNone(backend.reservation_state(bar()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
