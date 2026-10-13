# SPDX-License-Identifier: GPL-2.0-or-later
"""Bootstrap/version/capability regressions; no host, GUI, key or OS action runs."""
import copy
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import notification_history as history, notification_system as system
from blui_desktop import notification_system_native as system_native, notification_toolbar_native as toolbar
from blui_desktop import notification_uia_native as uia, notification_wire as wire
from blui_desktop.notification_metadata_native import NotifyItem, text as bounded_text
from blui_desktop import notification_path_native as paths
from blui_desktop import notification_toolbar_pixels as glyphs

OWNER = (10, 20, '30', 'Shell_TrayWnd')
SOURCE = (100, OWNER)
PROVIDER = (50, (10, 21, '30', 'ToolbarWindow32'))


def desc(index, *, class_name='', control_type=50021, name='', native=0, automation_id=''):
    return {'pid': 10, 'enabled': True, 'type': control_type, 'class': class_name,
        'id': automation_id, 'name': name, 'runtime': (42, index), 'handle': native,
        'rect': (100, 100, 124, 124)}


class Session:
    def __init__(self):
        self.nodes = {1: desc(1, class_name='Shell_TrayWnd', native=100),
                      2: desc(2, class_name='TrayNotifyWnd'),
                      3: desc(3, class_name='ToolbarWindow32', native=50),
                      4: desc(4, control_type=50000, name='Own fixture')}
        self.children, self.next, self.closed = {1: 2, 2: 3, 3: 4}, {}, False
        self.pattern = True
    def element(self, handle):
        if handle != SOURCE[0]:
            raise ValueError('Wrong scope')
        return c.c_void_p(1)
    def describe(self, element):
        return copy.deepcopy(self.nodes[element.value])
    def runtime_id(self, element):
        return self.nodes[element.value]['runtime']
    def child(self, element, *, sibling=False):
        return c.c_void_p((self.next if sibling else self.children).get(element.value, 0))
    def action_pattern(self, _element):
        return (c.c_void_p(900), 3) if self.pattern else (None, None)
    def close(self):
        self.closed = True


class Metadata:
    def __init__(self, *_args):
        self.rows, self.closed = [], False
    def snapshot(self):
        return copy.deepcopy(self.rows)
    def close(self):
        self.closed = True


def snapshot(rows=None, build=19045):
    return {'enabled': True, 'error': '', 'revision': 1, 'host_handle': '500',
        'icons': rows or [], 'platform': build, 'controls': system.controls(build),
        'bootstrap': {'state': 'READY', 'count': len(rows or []), 'error': ''}}


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.identity = lambda handle: OWNER if handle == 100 else PROVIDER[1] if handle == 50 else None
        self.bridge = history.Bridge(lambda: SOURCE, self.identity,
            session_factory=lambda: self.session, metadata_factory=Metadata, overflow_factory=lambda *_args: [])
        self.bridge.pixel_fallback = lambda *_args, **_kwargs: (0, 0, '')
        self.release = mock.patch.object(uia, 'release')
        self.release.start()
    def tearDown(self):
        self.bridge.close()
        self.release.stop()

    def test_token_changes_with_process_creation_or_runtime_id(self):
        first = history.token(SOURCE, (42, 4))
        self.assertEqual(len(first), 68)
        self.assertNotEqual(first, history.token((100, (10, 20, '31', 'Shell_TrayWnd')), (42, 4)))
        self.assertNotEqual(first, history.token(SOURCE, (42, 5)))

    def test_tray_scope_excludes_taskbar_app_buttons_and_wrong_pid(self):
        item = desc(9, control_type=50000, name='Not tray')
        self.assertFalse(history.eligible(item, scoped=False, explorer_pid=10))
        self.assertFalse(history.eligible(dict(item, pid=11), scoped=True, explorer_pid=10))
        self.assertFalse(history.eligible(dict(item, id='ShowDesktopStack'), scoped=True, explorer_pid=10))

    def test_win11_only_real_provider_default_action_no_guessed_callback(self):
        with mock.patch.object(system, 'build_number', return_value=22631), mock.patch.object(uia, 'call', return_value=0) as invoked:
            rows, _state = self.bridge.refresh()
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]['backend'], rows[0]['callback'], rows[0]['version'], rows[0]['actions']), ('UIA', 0, 0, ['LEFT']))
            self.bridge.action(rows[0]['key'], 'LEFT')
            invoked.assert_called_once()
            with self.assertRaises(ValueError):
                self.bridge.action(rows[0]['key'], 'RIGHT')

    def test_win10_toolbar_delegates_right_and_double_without_app_message_guess(self):
        with mock.patch.object(system, 'build_number', return_value=19045), mock.patch.object(toolbar, 'action', return_value=True) as delivered:
            rows, _state = self.bridge.refresh()
            self.assertEqual(rows[0]['backend'], 'TOOLBAR')
            for event in ('LEFT', 'RIGHT', 'DOUBLE', 'HOVER_ENTER', 'HOVER_LEAVE'):
                self.bridge.action(rows[0]['key'], event)
                self.assertEqual(delivered.call_args.args[:2], (SOURCE, PROVIDER))
                self.assertEqual(delivered.call_args.args[3], event)

    def test_stale_name_or_restarted_provider_never_invoked(self):
        with mock.patch.object(system, 'build_number', return_value=22631), mock.patch.object(uia, 'call', return_value=0) as invoked:
            rows, _state = self.bridge.refresh()
            self.session.nodes[4]['name'] = 'Different app'
            with self.assertRaises(ValueError):
                self.bridge.action(rows[0]['key'], 'LEFT')
            invoked.assert_not_called()
            self.bridge.find_source = lambda: (100, (10, 20, '999', 'Shell_TrayWnd'))
            with self.assertRaises(ValueError):
                self.bridge.action(rows[0]['key'], 'LEFT')
            invoked.assert_not_called()

    def test_metadata_only_never_claims_callback_or_version(self):
        self.session.nodes[4]['pid'] = 99
        self.bridge.metadata.rows = [{'handle': 700, 'uid': 3, 'guid': '', 'tip': 'Historical',
            'identity': (200, 201, '202', 'Own fixture'), 'hidden': True, 'pixels': (0, 0, '')}]
        with mock.patch.object(system, 'build_number', return_value=22631):
            rows, state = self.bridge.refresh()
        self.assertEqual(state['state'], 'PARTIAL')
        self.assertEqual((rows[0]['backend'], rows[0]['actions'], rows[0]['callback']), ('DISPLAY', [], 0))

    def test_user_requested_overflow_requires_exact_live_metadata_and_unique_target(self):
        from blui_desktop import notification_explorer_native as explorer
        owner = (200, 201, '202', 'Own fixture')
        self.bridge.identity = lambda handle: owner if handle == 700 else OWNER if handle == 100 else PROVIDER[1] if handle == 50 else None
        self.bridge.metadata.rows = [{'handle': 700, 'uid': 3, 'guid': '', 'tip': 'Historical',
            'identity': owner, 'hidden': True, 'pixels': (0, 0, '')}]
        self.session.nodes[4]['pid'] = 99
        with mock.patch.object(system, 'build_number', return_value=19045):
            rows, _state = self.bridge.refresh()
        self.assertEqual(rows[0]['backend'], 'OVERFLOW')
        target = dict(history.row_for(SOURCE, desc(4, name='Historical')), backend='TOOLBAR',
            actions=sorted(wire.EVENTS), button_rect=[100, 100, 124, 124], toolbar_handle='50', toolbar_thread=21)
        state = {'container': (60, (10, 22, '30', 'NotifyIconOverflowWindow')), 'target': None, 'input': None}
        with mock.patch.object(explorer, 'open_overflow', return_value=state) as opened, \
                mock.patch.object(explorer, 'close_overflow') as closed, mock.patch.object(self.bridge, '_walk', return_value=([target], True)):
            self.bridge.action(rows[0]['key'], 'RIGHT')
            opened.assert_called_once()
            closed.assert_called_once()
        self.bridge.metadata.rows[0]['tip'] = 'Changed app'
        with mock.patch.object(explorer, 'open_overflow') as opened:
            with self.assertRaises(ValueError):
                self.bridge.action(rows[0]['key'], 'RIGHT')
            opened.assert_not_called()

    def test_system_ui_uses_scoped_provider_before_fixed_fallback(self):
        self.session.nodes[4]['id'] = 'ControlCenterButton'
        with mock.patch.object(system, 'build_number', return_value=22631), mock.patch.object(uia, 'call', return_value=0) as invoked, mock.patch.object(system_native, 'action') as fallback:
            self.bridge.system('VOLUME', 'LEFT')
            invoked.assert_called_once()
            fallback.assert_not_called()
            self.bridge.system('VOLUME', 'RIGHT')
            fallback.assert_called_once_with('VOLUME', 'RIGHT')


class WireCapabilitiesTests(unittest.TestCase):
    def test_old_header_remains_exactly_compatible(self):
        self.assertEqual(wire.validate_snapshot(wire.empty()), (wire.empty(), {}))

    def test_system_commands_are_fixed_key_event_not_uri_or_foreign_hwnd(self):
        value, _pixels = wire.validate_snapshot(snapshot(build=22631))
        self.assertEqual(wire.callback('system:NETWORK', 'LEFT', 0, 0, value),
                         {'command': 'system', 'key': 'NETWORK', 'event': 'LEFT'})
        for key, event in [('system:cmd.exe', 'LEFT'), ('system:NETWORK', 'HOVER_ENTER')]:
            with self.assertRaises(ValueError):
                wire.callback(key, event, 0, 0, value)

    def test_uia_right_or_spoofed_true_callback_rejected(self):
        row = history.row_for(SOURCE, desc(4, name='Historical'), actionable=True)
        value, _pixels = wire.validate_snapshot(snapshot([row], build=22631))
        self.assertEqual(wire.callback(row['key'], 'LEFT', 0, 0, value)['command'], 'activate')
        with self.assertRaises(ValueError):
            wire.callback(row['key'], 'RIGHT', 0, 0, value)
        for candidate in [dict(row, callback=0x8001), dict(row, version=4), dict(row, actions=['LEFT', 'RIGHT']), dict(row, actions=[{}])]:
            with self.assertRaises(ValueError):
                wire.validate_snapshot(snapshot([candidate], build=22631))

    def test_toolbar_capability_cannot_be_enabled_on_win11(self):
        row = dict(history.row_for(SOURCE, desc(4, name='Historical')), backend='TOOLBAR', actions=sorted(wire.EVENTS),
                   button_rect=[100, 100, 124, 124], toolbar_handle='50', toolbar_thread=21)
        value, _pixels = wire.validate_snapshot(snapshot([row]))
        self.assertEqual(wire.callback(row['key'], 'DOUBLE', 0, 0, value)['event'], 'DOUBLE')
        with self.assertRaises(ValueError):
            wire.validate_snapshot(snapshot([row], build=22631))

    def test_overflow_wire_has_no_guessed_callback_and_is_click_only_win10(self):
        row = {'key': 'hwnd:700:3', 'handle': '700', 'uid': 3, 'guid': '', 'callback': 0,
               'version': 0, 'tip': 'Historical', 'hidden': True, 'width': 0, 'height': 0, 'rgba': '',
               'pid': 200, 'thread_id': 201, 'process_started': '202', 'window_class': 'Own fixture',
               'backend': 'OVERFLOW', 'actions': ['LEFT', 'RIGHT', 'DOUBLE']}
        value, _pixels = wire.validate_snapshot(snapshot([row]))
        self.assertEqual(wire.callback(row['key'], 'RIGHT', 0, 0, value)['command'], 'activate')
        with self.assertRaises(ValueError):
            wire.callback(row['key'], 'HOVER_ENTER', 0, 0, value)
        with self.assertRaises(ValueError):
            wire.validate_snapshot(snapshot([row], build=22631))

    def test_private_disabled_snapshot_cannot_expose_real_system_entry(self):
        value = dict(wire.empty(), platform=22631, controls=system.controls(22631))
        with self.assertRaises(ValueError):
            wire.validate_snapshot(value)
        self.assertEqual(system.controls(22631, private=True), [])


class SystemAndToolbarTests(unittest.TestCase):
    def test_original_toolbar_glyph_only_crops_requested_icon_rect(self):
        import base64
        raw = bytearray(bytes((10, 10, 10, 0)) * 24 * 24)
        for y in range(8, 16):
            for x in range(8, 16):
                raw[(y * 24 + x) * 4:(y * 24 + x + 1) * 4] = bytes((0, 0, 255, 0))
        size_x, size_y, value = glyphs.crop_glyph(bytes(raw), 24, 24, (0, 0, 24, 24))
        output = base64.b64decode(value)
        self.assertEqual((size_x, size_y), (32, 32))
        self.assertEqual(output[(16 * 32 + 16) * 4:(16 * 32 + 16 + 1) * 4], bytes((255, 0, 0, 255)))
        self.assertEqual(output[:4], bytes(4))
        with self.assertRaises(ValueError):
            glyphs.crop_glyph(bytes(raw), 24, 24, (0, 0, 4, 4))

    def test_com_lpwstr_stops_at_actual_nul_not_python_truthiness(self):
        value = c.create_unicode_buffer('Own fixture')
        self.assertEqual(bounded_text(c.addressof(value), 127), 'Own fixture')
        self.assertEqual(bounded_text(None, 127), '')

    def test_known_folder_and_long_nt_prefix_paths_match_real_executable(self):
        folder = '{d65231b0-b2f1-4857-a4ce-a8e7c6ea7d27}\\taskmgr.exe'
        self.assertEqual(paths.form(folder), 'KNOWN_FOLDER')
        self.assertEqual(paths.expand(folder, lambda _guid: 'C:\\Windows\\System32'),
                         paths.expand('\\\\?\\C:\\WINDOWS\\System32\\taskmgr.exe'))
        with self.assertRaises(ValueError):
            paths.expand('{d65231b0-b2f1-4857-a4ce-a8e7c6ea7d27}\\..\\evil.exe', lambda _guid: 'C:\\Windows')

    def test_documented_shortcuts_are_version_specific_and_paired(self):
        self.assertEqual(system.request('NOTIFICATIONS', 'LEFT', 19045)['value'], ['WIN', 'A'])
        self.assertEqual(system.request('NOTIFICATIONS', 'LEFT', 22631)['value'], ['WIN', 'N'])
        self.assertEqual(system_native.keyboard_plan(['WIN', 'A']), [(0x5b, False), (0x41, False), (0x41, True), (0x5b, True)])
        with self.assertRaises(ValueError):
            system_native.keyboard_plan(['WIN', 'R'])

    def test_private_system_action_rejected_before_native_api(self):
        with mock.patch.object(c, 'WinDLL', side_effect=AssertionError('No native call')):
            with self.assertRaises(ValueError):
                system_native.action('NETWORK', 'LEFT', private=True)

    def test_toolbar_coordinates_and_messages_are_pointer_free(self):
        self.assertEqual(toolbar.center((4, 6, 28, 30), (0, 0, 80, 40)), (16, 18))
        self.assertEqual(toolbar.plan('RIGHT', 16, 18), [(0x204, 2, 16 | (18 << 16)), (0x205, 0, 16 | (18 << 16))])
        self.assertEqual(toolbar.plan('DOUBLE', 16, 18)[0][0], 0x203)
        for rect in ((-1, 6, 28, 30), (4, 6, 81, 30), (4, 6, 4, 30), (4, 6, 28, 100)):
            with self.assertRaises(ValueError):
                toolbar.center(rect, (0, 0, 80, 40))

    def test_toolbar_rejects_win11_before_any_os_call(self):
        with mock.patch.object(c, 'WinDLL', side_effect=AssertionError('No native call')):
            with self.assertRaises(ValueError):
                toolbar.action(SOURCE, PROVIDER, (1, 1, 25, 25), 'LEFT', build=22631)

    def test_native_abi_matches_sdk_on_windows_x64(self):
        if sys.platform != 'win32' or c.sizeof(c.c_void_p) != 8:
            self.skipTest('Windows x64 ABI')
        self.assertEqual(c.sizeof(uia.GUID), 16)
        self.assertEqual(c.sizeof(NotifyItem), 56)
        self.assertEqual(NotifyItem.guid.offset, 40)
        self.assertEqual(c.sizeof(system_native._Input), 40)


if __name__ == '__main__':
    unittest.main(verbosity=2)
