# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure desktop transaction/IPC regression. Never starts a host or touches Explorer."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import desktop_host, desktop_host_state as state
from blui_desktop.desktop_host_watchdog import command
from blui_desktop.desktop_host_native import DesktopWindows

NONCE = 'a' * 32


def ident(handle='1', name='GHOST_WindowClass', pid=7):
    return {'handle': handle, 'pid': pid, 'thread_id': 9,
            'process_started': '123', 'window_class': name}


def shell(visible=True):
    return {'root': ident('10', 'Progman', 42), 'host': ident('11', 'WorkerW', 42),
            'view': ident('12', 'SHELLDLL_DefView', 42), 'list': ident('13', 'SysListView32', 42),
            'visible': visible, 'raised': False}


def surface(handle='1', device='DISPLAY1', rect=(0, 0, 1920, 1040)):
    return {'handle': handle, 'device': device, 'rect': list(rect)}


def canvas(row=None, host=None):
    row = row or surface()
    return {'window': ident(row['handle']), 'instance': '456', 'owner': None, 'host': (host or shell())['host'],
            'style': 0x80000000, 'extended_style': 0x80, 'rect': [0, 0, 800, 600],
            'visible': True, 'surface': deepcopy(row)}


class MemoryJournal:
    def __init__(self, value=None, events=None):
        self.value, self.events = deepcopy(value), events if events is not None else []

    def read(self):
        return deepcopy(self.value)

    def write(self, value):
        self.value = deepcopy(state.payload(value))
        self.events.append(('journal', len(value['canvases'])))


class Backend:
    def __init__(self, events, visible=True):
        self.events, self.original = events, shell(visible)
        self.shell_alive, self.topology_valid = True, True
        self.fail_attach, self.fail_restore = None, set()
        self.attached_handles = set()

    def discover(self):
        self.events.append(('discover',))
        return deepcopy(self.original)

    def validate_displays(self, rows):
        if not self.topology_valid:
            raise RuntimeError('displays changed')

    def capture(self, row, host):
        return canvas(row, host)

    def attach(self, row, host):
        self.events.append(('attach', row['window']['handle']))
        self.attached_handles.add(row['window']['handle'])
        return row['window']['handle'] != self.fail_attach

    def hide_icons(self, host):
        self.events.append(('hide', host['visible']))
        return True

    def restore_icons(self, host):
        self.events.append(('restore_icons', host['visible']))
        return True

    def restore_canvas(self, row):
        handle = row['window']['handle']
        self.events.append(('restore_canvas', handle))
        if handle in self.fail_restore:
            return False
        self.attached_handles.discard(handle)
        return True

    def attached(self, row, host):
        return row['window']['handle'] in self.attached_handles

    def matches_shell(self, host):
        return self.shell_alive


class DesktopStateTests(unittest.TestCase):
    def test_identity_rejects_bool_reused_and_unknown(self):
        for field, value in (('pid', True), ('thread_id', 0), ('handle', '0'),
                             ('process_started', ''), ('window_class', '\x00bad')):
            row = ident()
            row[field] = value
            with self.assertRaises(ValueError):
                state.identity(row)
        self.assertNotEqual(state.key(ident()), state.key(dict(ident(), process_started='124')))

    def test_only_native_desktop_canvas_classes(self):
        row = canvas()
        row['window']['window_class'] = 'BLUI_DesktopWindowClass'
        self.assertEqual(state.canvas_record(row)['window']['window_class'], 'BLUI_DesktopWindowClass')
        row['window']['window_class'] = 'SomeOtherWindow'
        with self.assertRaises(ValueError):
            state.canvas_record(row)

    def test_surface_duplicates_and_bounds(self):
        for rows in ([], [surface(), surface()], [surface(), surface('2')],
                     [dict(surface(), rect=[0, 0, 0, 10])], [dict(surface(), handle=1)]):
            with self.assertRaises(ValueError):
                state.surfaces(rows)
        self.assertEqual(state.surfaces([surface('2', 'DISPLAY2', (-1920, 0, 0, 1080))])[0]['rect'][0], -1920)

    def test_journal_roundtrip_utf8_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = state.Journal(directory)
            self.assertIsNone(journal.read())
            value = {'version': 1, 'nonce': NONCE, 'shell': shell(),
                     'canvases': [canvas(surface(device='显示器一'))]}
            journal.write(value)
            self.assertEqual(journal.read(), value)
            raw = Path(journal.path).read_bytes()
            self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
            self.assertIn('显示器一'.encode('utf-8'), raw)
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_no_partial_write_replaces_good_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = state.Journal(directory)
            value = {'version': 1, 'nonce': NONCE, 'shell': shell(), 'canvases': [canvas()]}
            journal.write(value)
            bad = deepcopy(value)
            bad['canvases'][0]['style'] |= 0x40000000
            with self.assertRaises(ValueError):
                journal.write(bad)
            self.assertEqual(journal.read(), value)

    def test_shell_mixed_owner_chain_rejected(self):
        value = shell()
        value['list']['pid'] = 99
        with self.assertRaises(ValueError):
            state.shell_record(value)

    def test_progman_host_must_be_exact_getshellwindow_root(self):
        value = shell()
        value['host']['window_class'] = 'Progman'
        with self.assertRaises(ValueError):
            state.shell_record(value)
        value['host'] = deepcopy(value['root'])
        self.assertEqual(state.shell_record(value)['host'], value['root'])

    def test_guard_journals_before_parenting_or_hiding(self):
        events = []
        guard = state.Guard(Backend(events), MemoryJournal(events=events), NONCE)
        self.assertTrue(guard.reconcile([surface()]))
        saved = events.index(('journal', 1))
        self.assertLess(saved, events.index(('attach', '1')))
        self.assertLess(saved, events.index(('hide', True)))
        self.assertTrue(guard.status()['enabled'])

    def test_failed_second_attach_restores_every_canvas_and_icons_first(self):
        events = []
        backend = Backend(events)
        backend.fail_attach = '2'
        guard = state.Guard(backend, MemoryJournal(events=events), NONCE)
        self.assertFalse(guard.reconcile([surface(), surface('2', 'DISPLAY2')]))
        self.assertNotIn(('hide', True), events)
        icons = events.index(('restore_icons', True))
        self.assertLess(icons, events.index(('restore_canvas', '1')))
        self.assertLess(icons, events.index(('restore_canvas', '2')))
        self.assertEqual(backend.attached_handles, set())
        self.assertFalse(guard.status()['pending_restore'])

    def test_removed_monitor_restores_and_requests_rebind(self):
        events = []
        backend = Backend(events)
        guard = state.Guard(backend, MemoryJournal(), NONCE)
        self.assertTrue(guard.reconcile([surface()]))
        backend.topology_valid = False
        self.assertFalse(guard.refresh())
        self.assertTrue(guard.status()['need_rebind'])
        self.assertFalse(guard.enabled)
        self.assertFalse(guard.value['canvases'])

    def test_shell_restart_does_not_silently_rehide_new_shell(self):
        events = []
        backend = Backend(events)
        guard = state.Guard(backend, MemoryJournal(), NONCE)
        guard.reconcile([surface()])
        backend.shell_alive = False
        count = sum(event[0] == 'hide' for event in events)
        guard.refresh()
        guard.refresh()
        self.assertEqual(sum(event[0] == 'hide' for event in events), count)
        self.assertTrue(guard.status()['need_rebind'])

    def test_failed_restore_retains_durable_record_and_blocks_new_attach(self):
        events = []
        backend = Backend(events)
        journal = MemoryJournal()
        guard = state.Guard(backend, journal, NONCE)
        guard.reconcile([surface()])
        backend.fail_restore.add('1')
        self.assertFalse(guard.restore())
        self.assertTrue(guard.status()['pending_restore'])
        self.assertEqual(journal.value['canvases'][0]['window']['handle'], '1')
        with self.assertRaises(RuntimeError):
            guard.reconcile([surface('2', 'DISPLAY2')])

    def test_idempotent_reconcile_has_no_new_parent_mutation(self):
        events = []
        guard = state.Guard(Backend(events), MemoryJournal(), NONCE)
        guard.reconcile([surface()])
        guard.reconcile([surface()])
        self.assertEqual(events.count(('attach', '1')), 1)

    def test_saved_hidden_icon_state_preserved(self):
        events = []
        guard = state.Guard(Backend(events, visible=False), MemoryJournal(), NONCE)
        guard.reconcile([surface()])
        guard.restore()
        self.assertIn(('restore_icons', False), events)
        self.assertNotIn(('restore_icons', True), events)

    def test_stale_guard_nonce_cannot_replay_new_transaction(self):
        journal = MemoryJournal({'version': 1, 'nonce': 'b' * 32, 'shell': shell(), 'canvases': [canvas()]})
        self.assertIsNone(state.recovery_snapshot(journal, NONCE))
        self.assertIsNotNone(state.recovery_snapshot(journal, 'b' * 32))


class NativeSafetyTests(unittest.TestCase):
    def backend(self):
        result = object.__new__(DesktopWindows)
        result.user = mock.Mock()
        result.user.GetPropW.return_value = 456
        result.owner_pid, result.owner_started, result.abort = 7, '123', None
        return result

    def test_dpi_mismatch_never_parent_or_style_mutates(self):
        backend = self.backend()
        backend.current = mock.Mock(return_value=ident())
        backend.matches = mock.Mock(return_value=True)
        backend.matches_shell = mock.Mock(return_value=True)
        backend.user.GetPropW.return_value = 1
        backend.user.GetWindowDpiAwarenessContext.side_effect = [1, 2]
        backend.user.AreDpiAwarenessContextsEqual.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'DPI'):
            backend.capture(surface(), shell())
        backend.user.SetParent.assert_not_called()
        backend.user.SetWindowLongPtrW.assert_not_called()
        backend.user.SetWindowPos.assert_not_called()

    def test_missing_marker_refused(self):
        backend = self.backend()
        backend.current = mock.Mock(return_value=ident())
        backend.matches = mock.Mock(return_value=True)
        backend.user.GetPropW.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'marker'):
            backend.capture(surface(), shell())
        backend.user.SetParent.assert_not_called()

    def test_reused_child_identity_never_restore(self):
        backend = self.backend()
        backend.matches = mock.Mock(return_value=False)
        self.assertTrue(backend.restore_canvas(canvas()))
        backend.user.SetParent.assert_not_called()
        backend.user.SetWindowLongPtrW.assert_not_called()

    def test_recycled_hwnd_same_process_thread_class_new_instance_never_restore(self):
        backend = self.backend()
        backend.matches = mock.Mock(return_value=True)
        backend.user.GetPropW.return_value = 457
        self.assertTrue(backend.restore_canvas(canvas()))
        backend.user.SetParent.assert_not_called()
        backend.user.SetWindowLongPtrW.assert_not_called()

    def test_unrelated_new_parent_never_detached(self):
        backend = self.backend()
        backend.matches = mock.Mock(return_value=True)
        backend.user.GetWindowLongPtrW.return_value = 0x40000000
        backend.user.GetParent.return_value = 999
        self.assertFalse(backend.restore_canvas(canvas()))
        backend.user.SetParent.assert_not_called()

    def test_null_setparent_does_not_demand_none_before_clearing_child_style(self):
        backend = self.backend()
        backend.user.SetParent.return_value = 11
        backend.user.GetParent.return_value = 999  # Intermediate Desktop HWND.
        self.assertTrue(backend._parent(1, None))

    def test_partial_detach_desktop_parent_can_finish_rollback_not_foreign(self):
        backend = self.backend()
        backend.matches = mock.Mock(return_value=True)
        backend.user.GetDesktopWindow.return_value = 999
        backend.user.GetParent.return_value = 999
        backend.user.GetWindowLongPtrW.side_effect = [0x40000000, 0x40000000, 0x80,
                                                    0x80000000, 0x80000000, 0x80]
        backend.user.GetWindow.return_value = None
        backend._parent = mock.Mock(return_value=True)
        backend._long = mock.Mock()
        backend._rect = mock.Mock(return_value=canvas()['rect'])
        self.assertTrue(backend.restore_canvas(canvas()))
        backend._long.assert_any_call(1, -16, 0x80000000)

    def test_restoration_does_not_require_marker(self):
        backend = self.backend()
        backend.matches = mock.Mock(return_value=True)
        backend.user.GetWindowLongPtrW.side_effect = [0x80000000, 0x80000000, 0x80,
                                                    0x80000000, 0x80000000, 0x80]
        backend._long = mock.Mock()
        backend.user.GetWindow.return_value = None
        backend._rect = mock.Mock(return_value=canvas()['rect'])
        self.assertTrue(backend.restore_canvas(canvas()))
        self.assertTrue(all(call.args[1] == 'BLUI.DesktopInstance.v1'
                            for call in backend.user.GetPropW.call_args_list))
        backend._long.assert_not_called()  # Exact already-restored state requires no risky foreign-thread write.

    def test_async_geometry_waits_without_losing_journal_or_rewriting_owner(self):
        backend = self.backend()
        backend.matches = mock.Mock(return_value=True)
        backend.user.GetWindowLongPtrW.side_effect = [0x80000000, 0x80000000, 0x80]
        backend.user.GetWindow.return_value = None
        backend._long = mock.Mock(side_effect=AssertionError('unchanged owner/style must not be written'))
        backend._rect = mock.Mock(return_value=[0, 0, 1920, 1040])
        self.assertFalse(backend.restore_canvas(canvas()))
        self.assertIn('geometry restoration pending', backend.restore_error)

    def test_reused_shell_identity_never_shown(self):
        backend = self.backend()
        backend.matches_shell = mock.Mock(return_value=False)
        self.assertTrue(backend.restore_icons(shell()))
        backend.user.SetWindowPos.assert_not_called()

    def test_original_hidden_icons_not_shown(self):
        backend = self.backend()
        self.assertTrue(backend.restore_icons(shell(False)))
        backend.user.SetWindowPos.assert_not_called()


class ProtocolTests(unittest.TestCase):
    def test_command_strict_allowlist(self):
        self.assertEqual(command({'command': 'reconcile', 'serial': 1, 'surfaces': [surface()]}),
                         {'command': 'reconcile', 'serial': 1, 'surfaces': [surface()]})
        for value in ('heartbeat', {'command': 'execute', 'path': 'bad'},
                      {'command': 'shutdown', 'extra': 1}, {'command': 'reconcile', 'serial': 1, 'surfaces': []},
                      {'command': 'restore', 'serial': True}, {'command': 'restore', 'serial': 0}):
            with self.assertRaises(ValueError):
                command(value)

    def test_client_status_validation_and_copy(self):
        value = dict(desktop_host._default, handles=[])
        result = desktop_host.status(value)
        result['handles'].append('1')
        self.assertEqual(value['handles'], [])
        for bad in (dict(value, attached_count=True), dict(value, handles=['1']),
                    dict(value, error='\x00'), dict(value, enabled='yes')):
            with self.assertRaises(ValueError):
                desktop_host.status(bad)

    def test_facade_is_ram_only_latest_topology_restore_not_dropped(self):
        controller = object.__new__(desktop_host.Controller)
        controller._lock = threading.Lock()
        controller._wake, controller._stopping = threading.Event(), threading.Event()
        controller._commands = __import__('collections').deque(maxlen=32)
        controller._serial = 0
        with mock.patch('subprocess.Popen', side_effect=AssertionError('no native process')):
            self.assertEqual(controller.request('reconcile', [surface()]), 1)
            self.assertEqual(controller.request('restore'), 2)
        self.assertEqual(list(controller._commands), [{'command': 'restore', 'serial': 2}])
        self.assertTrue(controller._wake.is_set())

    def test_restore_of_stopped_controller_restarts_same_directory(self):
        previous = mock.Mock(directory='D:/test')
        previous._stopping.is_set.return_value = True
        fresh = mock.Mock()
        fresh.request.return_value = 5
        with mock.patch.object(desktop_host, '_controller', previous), \
                mock.patch.object(desktop_host, 'start', return_value=fresh) as start:
            self.assertEqual(desktop_host.restore(), 5)
        start.assert_called_once_with('D:/test')
        fresh.request.assert_called_once_with('restore')


if __name__ == '__main__':
    unittest.main()
