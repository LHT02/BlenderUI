# SPDX-License-Identifier: GPL-2.0-or-later
"""Start-menu regressions. Only owned temporary files; never starts or powers off anything."""
import copy
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
from blui_desktop import start_menu, start_menu_backend as backend, start_menu_model as schema


def program(name='Calculator', source='user', relative=None):
    relative = relative or name + '.lnk'
    return {'id': schema.app_id(source, relative), 'name': name, 'source': source,
            'relative': relative, 'path': 'C:\\Programs\\' + relative, 'group': '',
            'signature': {'mtime_ns': 10, 'size': 20, 'device': 1, 'inode': 2}}


def index(rows=None, revision=0, pins=None, recent=None):
    return dict(schema.empty_state(), rows=rows or [program()], revision=revision,
                pins=pins or [], recent=recent or [], errors=[], truncated=False)


class ModelTests(unittest.TestCase):
    def test_index_clean_and_response_limits(self):
        result = schema.validate_index(index())
        self.assertEqual(result['rows'][0]['name'], 'Calculator')
        for field, replacement in (('rows', [program()] * 1025), ('truncated', 1),
                                   ('errors', ['error'] * 33), ('revision', True), ('version', True)):
            value = index()
            value[field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                schema.validate_index(value)

    def test_relative_targets_cannot_escape_or_be_commands(self):
        for relative in ('..\\bad.exe', 'C:\\bad.exe', '\\\\host\\bad.lnk', '.\\bad.exe',
                         'x\\..\\bad.lnk', 'x.exe:stream', 'cmd /c x.exe && shutdown', 'app.url', 'a\\\\app.lnk'):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                schema.relative_path(relative)
        self.assertEqual(schema.relative_path('Folder/app.lnk'), 'Folder\\app.lnk')

    def test_program_signature_and_identity_are_strict(self):
        for field, replacement in (('id', 'a' * 64), ('source', 'arbitrary'),
                                   ('path', 'relative.exe'), ('name', ''), ('relative', '..\\bad.exe'),
                                   ('signature', {'mtime_ns': 1}), ('signature', {'mtime_ns': True, 'size': 2, 'device': 3, 'inode': 4})):
            row = program()
            row[field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                schema.program(row)

    def test_duplicate_index_and_pin_keys_rejected(self):
        with self.assertRaises(ValueError):
            schema.validate_index(index([program(), program()]))
        value = schema.empty_state()
        value['pins'] = [program()['id']] * 2
        with self.assertRaises(ValueError):
            schema.state(value)

    def test_search_is_unicode_name_category_only(self):
        a, b, c = program('Calculator'), program('画图'), program('Other Calculator')
        b['group'] = 'Windows Accessories / 工具'
        self.assertEqual(schema.search([c, b, a], 'ＣＡＬＣ')[0]['id'], a['id'])
        self.assertEqual(schema.search([c, b, a], '画图 工具'), [b])
        with mock.patch.object(os, 'startfile', create=True, side_effect=AssertionError('Search cannot launch')):
            self.assertEqual(schema.search([a], 'calc.exe && shutdown /s'), [])

    def test_selected_preserves_pin_order_and_ignores_removed(self):
        a, b = program('A'), program('B')
        self.assertEqual(schema.selected([a, b], [b['id'], 'f' * 64, a['id']]), [b, a])


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='blui_start_menu_qa_')
        self.root = Path(self.temporary.name)
        self.user, self.common = self.root / 'user', self.root / 'common'
        self.user.mkdir()
        self.common.mkdir()
        self.roots = {'user': str(self.user), 'common': str(self.common)}

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, relative, data=b'fixture', *, root=None):
        path = (root or self.user) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _row(self, relative='Tools/test.lnk'):
        self._write(relative)
        return backend.scan_programs(self.roots)['rows'][0]

    def test_scans_both_programs_folders_without_resolving_links(self):
        self._write('Tools/测试.lnk')
        self._write('Common.exe', root=self.common)
        self._write('Internet.url')
        self._write('Ignore.bat')
        result = backend.scan_programs(self.roots)
        self.assertEqual({row['name'] for row in result['rows']}, {'测试', 'Common'})
        self.assertEqual({row['source'] for row in result['rows']}, {'user', 'common'})
        self.assertEqual(next(row['group'] for row in result['rows'] if row['name'] == '测试'), 'Tools')
        self.assertFalse(result['truncated'])

    def test_redirected_duplicate_root_prefers_user_scope(self):
        self._write('same.lnk')
        rows = backend.scan_programs({'user': str(self.user), 'common': str(self.user)})['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source'], 'user')

    def test_scan_entry_time_depth_and_row_budgets(self):
        for name in ('a.lnk', 'b.exe', 'c.lnk'):
            self._write(name)
        with mock.patch.object(schema, 'MAX_APPS', 2):
            result = backend.scan_programs(self.roots)
            self.assertEqual(len(result['rows']), 2)
            self.assertTrue(result['truncated'])
        with mock.patch.object(backend, 'MAX_ENTRIES', 1):
            self.assertTrue(backend.scan_programs(self.roots)['truncated'])
        self.assertTrue(backend.scan_programs(self.roots, clock=mock.Mock(side_effect=[0, 0, 5, 5]))['truncated'])
        self._write('deep/inner/app.lnk')
        with mock.patch.object(backend, 'MAX_DEPTH', 0):
            rows = backend.scan_programs(self.roots)
            self.assertTrue(rows['truncated'])
            self.assertNotIn('app', [row['name'] for row in rows['rows']])

    def test_reparse_entries_are_skipped_and_unsafe_ancestor_rejected(self):
        row = self._row()
        with mock.patch.object(backend, '_reparse', return_value=True):
            self.assertEqual(backend.scan_programs(self.roots)['rows'], [])
            with self.assertRaisesRegex(ValueError, 'junction'):
                backend.validated_target(row, self.roots)

    def test_stale_size_mtime_or_file_id_cannot_launch(self):
        row = self._row()
        self.assertEqual(backend.validated_target(row, self.roots), row['path'])
        self._write('Tools/test.lnk', b'changed fixture')
        with self.assertRaisesRegex(ValueError, 'changed'):
            backend.validated_target(row, self.roots)

    def test_same_relative_path_under_new_root_cannot_launch(self):
        row = self._row()
        self._write('Tools/test.lnk', root=self.common)
        with self.assertRaisesRegex(ValueError, 'moved outside'):
            backend.validated_target(row, {'user': str(self.common)})
        row['path'] = str(self.root / 'outside.exe')
        with self.assertRaises(ValueError):
            backend.validated_target(row, self.roots)

    def test_atomic_save_backup_corruption_and_revision_conflicts(self):
        directory = str(self.root / 'config')
        first = dict(schema.empty_state(), revision=1, pins=[program()['id']])
        second = dict(first, revision=2, recent=[program('Recent')['id']])
        self.assertTrue(backend.start_state(directory, first))
        self.assertTrue(backend.start_state(directory, second))
        self.assertEqual(backend.load_state(directory), second)
        target = Path(directory) / 'start-menu.json'
        self.assertFalse(target.read_bytes().startswith(b'\xef\xbb\xbf'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            backend.start_state(directory, first)
        target.write_text('{broken', encoding='utf-8')
        self.assertEqual(backend.load_state(directory), first)
        self.assertTrue(backend.start_state(directory, second))
        self.assertEqual(json.loads(target.with_suffix('.bak').read_text(encoding='utf-8')), first)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            backend.start_state(directory, dict(second, pins=[]))

    def test_no_save_for_bad_preferences(self):
        directory = str(self.root / 'invalid-config')
        with self.assertRaises(ValueError):
            backend.start_state(directory, dict(schema.empty_state(), pins=['bad']))
        self.assertFalse(Path(directory).exists())

    def test_launch_uses_exact_path_and_revalidates_under_guard(self):
        row = self._row()
        @contextmanager
        def guard(path):
            self.assertEqual(path, row['path'])
            yield
        with mock.patch.object(backend, '_program_roots', return_value=self.roots), \
                mock.patch.object(backend, '_file_guard', guard), \
                mock.patch.object(backend, 'validated_target', wraps=backend.validated_target) as checked, \
                mock.patch.object(os, 'startfile', create=True) as started:
            self.assertTrue(backend.start_launch(row))
            started.assert_called_once_with(row['path'], 'open')
            self.assertEqual(checked.call_count, 2)

    def test_launch_refuses_change_between_first_check_and_guard(self):
        row = self._row()
        @contextmanager
        def guard(_path):
            self._write('Tools/test.lnk', b'changed during launch')
            yield
        with mock.patch.object(backend, '_program_roots', return_value=self.roots), \
                mock.patch.object(backend, '_file_guard', guard), \
                mock.patch.object(os, 'startfile', create=True) as started:
            with self.assertRaises(ValueError):
                backend.start_launch(row)
            started.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'The file identity guard is native Windows')
    def test_real_file_guard_denies_fixture_writes_but_permits_reads(self):
        row = self._row()
        path = Path(row['path'])
        with backend._file_guard(row['path']):
            self.assertEqual(path.read_bytes(), b'fixture')
            with self.assertRaises(OSError):
                path.write_bytes(b'not allowed while explicitly launching')
        self.assertEqual(path.read_bytes(), b'fixture')

    def test_system_actions_are_fixed_allowlist_and_settings_uri(self):
        for action in ('cmd /c calc', 'ms-settings:anything', '', None):
            with self.subTest(action=action), self.assertRaises(ValueError):
                backend.start_system(action)
        with mock.patch.object(os, 'startfile', create=True) as started:
            self.assertTrue(backend.start_system('SETTINGS'))
            self.assertTrue(backend.start_system('POWER_SETTINGS'))
            self.assertEqual(started.call_args_list, [mock.call('ms-settings:'), mock.call('ms-settings:powersleep')])
        # Power APIs are never exercised on this machine.
        with mock.patch.object(backend, '_shutdown') as power:
            backend.start_system('SHUTDOWN')
            backend.start_system('RESTART')
            self.assertEqual(power.call_args_list, [mock.call(False), mock.call(True)])


class Job:
    instances = []
    def __init__(self, action, *args, **_kwargs):
        self.action, self.args, self.value, self.error, self.ready, self.closed = action, args, None, None, False, False
        self.instances.append(self)
    def done(self):
        return self.ready
    def result(self):
        if self.error:
            raise RuntimeError(self.error)
        return self.value
    def close(self):
        self.closed = True
    def complete(self, value=None, error=None):
        self.value, self.error, self.ready = value, error, True


class FacadeTests(unittest.TestCase):
    def setUp(self):
        start_menu.close()
        Job.instances.clear()
        self.patch = mock.patch.object(start_menu.client, 'Job', Job)
        self.patch.start()
    def tearDown(self):
        start_menu.close()
        self.patch.stop()

    def _load(self, rows=None):
        start_menu.ensure('C:\\private-fixture\\config')
        Job.instances[-1].complete(index(rows))
        start_menu.tick()
        return Job.instances[-1]

    def test_ensure_and_snapshot_are_memory_only_and_single_flight(self):
        with mock.patch.object(os, 'stat', side_effect=AssertionError('No UI filesystem queries')):
            start_menu.ensure('C:\\private-fixture\\config')
            start_menu.ensure('C:\\private-fixture\\config')
            self.assertEqual(len(Job.instances), 1)
            self.assertTrue(start_menu.snapshot()['loading'])
            start_menu.tick()

    def test_index_and_local_pin_changes_during_refresh_are_preserved(self):
        self._load()
        start_menu.ensure('C:\\private-fixture\\config', refresh=True)
        refreshing = Job.instances[-1]
        start_menu.pin(program()['id'])
        refreshing.complete(index())
        start_menu.tick()
        self.assertEqual(start_menu.snapshot()['pins'], [program()['id']])

    def test_index_begun_before_save_ack_cannot_rewind_saved_pins(self):
        self._load()
        start_menu.pin(program()['id'])
        start_menu.ensure('C:\\private-fixture\\config', refresh=True)
        refreshing = Job.instances[-1]
        with mock.patch.object(start_menu.time, 'monotonic', return_value=time.monotonic() + 10):
            start_menu.tick()
            Job.instances[-1].complete(True)  # State write acknowledged before the older index replies.
            start_menu.tick()
        self.assertFalse(start_menu._dirty)
        refreshing.complete(index())
        start_menu.tick()
        self.assertEqual(start_menu.snapshot()['pins'], [program()['id']])
        self.assertEqual(start_menu.snapshot()['revision'], 1)

    def test_one_checked_launch_and_success_only_recent(self):
        self._load()
        start_menu.launch(program()['id'])
        launching = Job.instances[-1]
        with self.assertRaises(RuntimeError):
            start_menu.launch(program()['id'])
        self.assertEqual(start_menu.snapshot()['recent'], [])
        launching.complete(True)
        start_menu.tick()
        self.assertEqual(start_menu.snapshot()['recent'], [program()['id']])
        start_menu.launch(program()['id'])
        Job.instances[-1].complete(error='The program changed')
        start_menu.tick()
        self.assertIn('changed', start_menu.snapshot()['error'])
        self.assertEqual(start_menu.snapshot()['recent'], [program()['id']])

    def test_save_ack_does_not_clear_more_recent_edit(self):
        self._load([program('A'), program('B')])
        start_menu.pin(program('A')['id'])
        with mock.patch.object(start_menu.time, 'monotonic', return_value=time.monotonic() + 10):
            start_menu.tick()
            saving = Job.instances[-1]
            start_menu.pin(program('B')['id'])
            saving.complete(True)
            start_menu.tick()
            self.assertTrue(start_menu._dirty)
        self.assertEqual(start_menu.snapshot()['pins'], [program('A')['id'], program('B')['id']])

    def test_close_discards_owned_jobs_without_wait_or_late_results(self):
        self._load()
        start_menu.ensure('C:\\private-fixture\\config', refresh=True)
        refreshing = Job.instances[-1]
        start_menu.close()
        self.assertTrue(refreshing.closed)
        refreshing.complete(index([program('Late')]))
        start_menu.tick()
        self.assertEqual(start_menu.snapshot()['rows'], [])

    def test_save_conflict_stops_retries_until_explicit_refresh(self):
        self._load()
        start_menu.pin(program()['id'])
        with mock.patch.object(start_menu.time, 'monotonic', return_value=time.monotonic() + 10):
            start_menu.tick()
            saving = Job.instances[-1]
            saving.complete(error='Start menu preferences changed; refresh the menu')
            start_menu.tick()
            self.assertFalse(start_menu._dirty)
        self.assertIn('refresh', start_menu.snapshot()['error'])


class UIAvailabilityTests(unittest.TestCase):
    """Load the real UI adapter with minimal RNA doubles, without a Blender window."""
    def _adapter(self, operator):
        fake_bpy, fake_props, fake_types = ModuleType('bpy'), ModuleType('bpy.props'), ModuleType('bpy.types')
        for name in ('EnumProperty', 'IntProperty', 'PointerProperty', 'StringProperty'):
            setattr(fake_props, name, lambda **_kwargs: None)
        for name in ('Menu', 'Operator', 'Panel', 'PropertyGroup'):
            setattr(fake_types, name, type(name, (), {}))
        fake_bpy.types = fake_types
        fake_bpy.ops = SimpleNamespace(wm=SimpleNamespace(blui_shell_window_create=operator))
        icons, session = ModuleType('blui_desktop.icon_cache'), ModuleType('blui_desktop.session')
        with mock.patch.dict(sys.modules, {'bpy': fake_bpy, 'bpy.props': fake_props, 'bpy.types': fake_types,
                                           'blui_desktop.icon_cache': icons, 'blui_desktop.session': session}):
            spec = importlib.util.spec_from_file_location('blui_desktop._start_ui_fixture',
                      SOURCE / 'scripts/modules/blui_desktop/start_menu_ui.py')
            adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter)
        return adapter, fake_bpy

    def test_internal_c_operator_uses_rna_not_bpy_types_class_presence(self):
        lookup = mock.Mock(return_value=object())
        adapter, fake_bpy = self._adapter(SimpleNamespace(get_rna_type=lookup))
        self.assertFalse(hasattr(fake_bpy.types, 'WM_OT_blui_shell_window_create'))
        self.assertTrue(adapter._shell_windows_available())
        lookup.assert_called_once_with()

    def test_missing_operator_or_failed_rna_lookup_uses_fallback(self):
        for operator in (SimpleNamespace(), SimpleNamespace(get_rna_type=mock.Mock(side_effect=RuntimeError('not registered')))):
            adapter, _fake_bpy = self._adapter(operator)
            self.assertFalse(adapter._shell_windows_available())


if __name__ == '__main__':
    unittest.main(verbosity=2)
