# SPDX-License-Identifier: GPL-2.0-or-later
"""Desktop services: no bpy, GUI, user-window activation, or user-file mutation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts' / 'modules'))
from blui_desktop import client, model, native_windows, worker
from blui_explorer import mailbox


def payload(name='fixture'):
    return {'version': 1, 'directory': '', 'nodes': [
        {'kind': model.NOTE, 'location': [1.25, -30], 'name': name, 'note': '测试 note'}]}


class FakeProcess:
    def __init__(self, code=None, stuck=False):
        self.code, self.stuck, self.kills = code, stuck, 0

    def poll(self):
        return self.code

    def kill(self):
        self.kills += 1
        self.code = -9

    def wait(self, timeout):
        if self.stuck:
            raise subprocess.TimeoutExpired('private helper', timeout)
        return self.code


class DesktopServices(unittest.TestCase):
    def tearDown(self):
        with client._live_lock:
            jobs = list(client._live)
        client.close_all()
        for job in jobs:
            self.assertTrue(job._cleaned.wait(3), 'Owned desktop helper did not clean up')
        self.assertFalse(client._live)

    def test_scan_is_bounded_and_does_not_recurse(self):
        calls = []
        class Entry:
            name = 'test'
            path = 'private/test'
            def is_dir(self, *, follow_symlinks):
                calls.append(follow_symlinks)
                return True
        entries = mock.MagicMock()
        entries.__enter__.return_value = iter(Entry() for _ in range(model.LIMIT + 50))
        with mock.patch.object(model.os, 'scandir', return_value=entries):
            result = model.scan('explicit folder only')
        self.assertEqual(len(result['rows']), model.LIMIT)
        self.assertTrue(result['truncated'])
        self.assertEqual(calls, [False] * model.LIMIT)

    def test_explicit_paths_are_normalized_deduplicated_and_bounded(self):
        with tempfile.TemporaryDirectory(prefix='blui_desktop_paths_') as directory:
            folder = Path(directory) / 'child'
            folder.mkdir()
            file = Path(directory) / 'file.txt'
            file.write_text('fixture', encoding='utf-8')
            with mock.patch.object(model.os.path, 'realpath', side_effect=AssertionError('No resolving')):
                rows = model.inspect_paths([str(folder), str(folder / '.'), str(file)])
            self.assertEqual(len(rows), 2)
            self.assertTrue(rows[0]['folder'])
            self.assertFalse(rows[1]['folder'])
        for paths in ([None], ['bad\x00path'], ['x'] * (model.LIMIT + 1), 'not a list'):
            with self.assertRaises(ValueError):
                model.inspect_paths(paths)

    def test_schema_rejects_bad_types_nonfinite_and_unbounded_values(self):
        variants = []
        for location in ([True, 1], [float('nan'), 1], [float('inf'), 1], [10 ** 1000, 1]):
            item = payload()
            item['nodes'][0]['location'] = location
            variants.append(item)
        for field, value in (('kind', []), ('folder', 'false'), ('note', 'a' * 32769), ('path', 'a\x00b')):
            item = payload()
            item['nodes'][0][field] = value
            variants.append(item)
        item = payload()
        item['version'] = True
        variants.append(item)
        for item in variants:
            with self.assertRaises(ValueError):
                model.validate(item)

    def test_atomic_save_backup_recovers_corrupt_or_missing_json(self):
        with tempfile.TemporaryDirectory(prefix='blui_desktop_json_') as directory:
            target = Path(directory) / 'canvas.json'
            model.save(target, payload('first'))
            self.assertFalse(target.read_bytes().startswith(b'\xef\xbb\xbf'))
            model.save(target, payload('second'))
            self.assertEqual(model.load(target)['nodes'][0]['name'], 'second')
            target.write_text('{truncated', encoding='utf-8')
            self.assertEqual(model.load(target)['nodes'][0]['name'], 'first')
            model.save(target, payload('third'))
            target.unlink()
            self.assertEqual(model.load(target)['nodes'][0]['name'], 'first')
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_load_and_save_enforce_byte_limit(self):
        with tempfile.TemporaryDirectory(prefix='blui_desktop_limit_') as directory:
            target = Path(directory) / 'canvas.json'
            with mock.patch.object(model, 'MAX_BYTES', 40):
                with self.assertRaises(ValueError):
                    model.save(target, payload())
                target.write_bytes(b' ' * 41)
                with self.assertRaises(ValueError):
                    model.load(target)

    def test_real_worker_scan_paths_and_json(self):
        with tempfile.TemporaryDirectory(prefix='blui_desktop_worker_') as directory:
            folder = Path(directory) / 'folder'
            folder.mkdir()
            target = Path(directory) / 'layout.json'
            for action, args in (('scan', (directory,)), ('paths', ([str(folder)],)),
                                 ('save', (str(target), payload())), ('load', (str(target),))):
                job = client.Job(action, *args, timeout=5)
                deadline = time.monotonic() + 6
                while not job.done() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(job.done(), action)
                result = job.result()
                self.assertIsNotNone(result)
                self.assertTrue(job.closed)

    def test_concurrent_save_helpers_keep_complete_layout_and_backup(self):
        with tempfile.TemporaryDirectory(prefix='blui_desktop_concurrent_') as directory:
            target = Path(directory) / 'canvas.json'
            model.save(target, payload('initial'))
            jobs = [client.Job('save', str(target), payload(name), timeout=5)
                    for name in ('first concurrent', 'second concurrent', 'third concurrent')]
            deadline = time.monotonic() + 6
            for job in jobs:
                while not job.done() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(job.done())
                job.result()
            self.assertIn(model.load(target)['nodes'][0]['name'],
                          {'first concurrent', 'second concurrent', 'third concurrent'})
            backup = model.load(target.with_suffix('.bak'))
            self.assertNotEqual(backup['nodes'][0]['name'], model.load(target)['nodes'][0]['name'])
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_oversized_response_is_rejected_before_reading(self):
        process = FakeProcess()
        with mock.patch.object(client.subprocess, 'Popen', return_value=process), \
             mock.patch.object(model, 'MAX_BYTES', 40):
            job = client.Job('tasks')
            self.assertTrue(job._prepared.wait(2))
            oversized = Path(job.directory, 'oversized.tmp')
            oversized.write_bytes(b' ' * 41)
            os.replace(oversized, Path(job.directory, 'result.json'))
            self.assertTrue(job._finished.wait(2))
            with self.assertRaisesRegex(RuntimeError, 'too large'):
                job.result()
            self.assertTrue(job._cleaned.wait(2))
        self.assertEqual(process.kills, 1)

    def test_bad_request_gets_error_reply_from_real_worker(self):
        with tempfile.TemporaryDirectory(prefix='blui_desktop_request_') as directory:
            Path(directory, 'request.json').write_text('{bad json', encoding='utf-8')
            result = subprocess.run([sys.executable, '-I', '-B', str(SOURCE / 'scripts/modules/blui_desktop/worker.py'),
                                     directory], timeout=5, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(mailbox.take(directory, 'result.json')['ok'])

    @unittest.skipUnless(os.name == 'nt', 'Windows open service')
    def test_open_routes_only_explicit_path_without_command_shell(self):
        with tempfile.TemporaryDirectory(prefix='blui_desktop_open_') as directory:
            path = str(Path(directory) / 'test & no command.txt')
            mailbox.publish(directory, 'request.json', {'action': 'open', 'args': [path]})
            with mock.patch.object(worker.os, 'startfile') as start, \
                 mock.patch.object(worker.sys, 'argv', ['worker', directory]):
                worker.main()
                start.assert_called_once_with(os.path.abspath(path))
            self.assertTrue(mailbox.take(directory, 'result.json')['ok'])
            for path in (None, '', 'bad\x00path'):
                with self.assertRaises(ValueError):
                    client.Job('open', path)

    def test_bad_reply_does_not_escape_ui_poll(self):
        for value in ([], {'ok': 1}, {'ok': True, 'value': 'not task rows'}):
            process = FakeProcess()
            with mock.patch.object(client.subprocess, 'Popen', return_value=process):
                job = client.Job('tasks')
                self.assertTrue(job._prepared.wait(2))
                mailbox.publish(job.directory, 'result.json', value)
                self.assertTrue(job._finished.wait(2))
                with self.assertRaises(RuntimeError):
                    job.result()
                self.assertTrue(job._cleaned.wait(2))
            self.assertEqual(process.kills, 1)

    def test_result_read_lock_after_exit_is_retried(self):
        process, blocked, release = FakeProcess(0), threading.Event(), threading.Event()
        take = mailbox.take
        def temporarily_locked(*args):
            if not release.is_set():
                blocked.set()
                return None
            return take(*args)
        with mock.patch.object(client.subprocess, 'Popen', return_value=process), \
             mock.patch.object(client.mailbox, 'take', side_effect=temporarily_locked):
            job = client.Job('tasks')
            self.assertTrue(job._prepared.wait(2))
            mailbox.publish(job.directory, 'result.json', {'ok': True, 'value': []})
            self.assertTrue(blocked.wait(2))
            self.assertFalse(job.done())
            release.set()
            self.assertTrue(job._finished.wait(2))
            self.assertEqual(job.result(), [])
            self.assertTrue(job._cleaned.wait(2))
        self.assertEqual(process.kills, 0)

    def test_helper_exit_and_timeout_are_bounded_to_owned_process(self):
        for exited in (False, True):
            process, other, clock = FakeProcess(0 if exited else None, stuck=True), FakeProcess(), [100.0]
            with mock.patch.object(client.time, 'monotonic', side_effect=lambda: clock[0]), \
                 mock.patch.object(client.subprocess, 'Popen', return_value=process):
                job = client.Job('tasks', timeout=1)
                self.assertTrue(job._prepared.wait(2))
                self.assertFalse(job.done())
                if exited:
                    for _ in range(100):
                        if job.exited is not None:
                            break
                        threading.Event().wait(.01)
                    self.assertIsNotNone(job.exited)
                clock[0] += .6 if exited else 1.1
                self.assertTrue(job._finished.wait(2))
                with self.assertRaises(RuntimeError):
                    job.result()
                self.assertTrue(job._cleaned.wait(2))
            self.assertEqual(process.kills, 0 if exited else 1)
            self.assertEqual(other.kills, 0)

    def test_main_thread_job_api_does_not_touch_filesystem_or_process_api(self):
        main = threading.get_ident()
        touched = []
        def off_thread(name, function):
            def call(*args, **kwargs):
                self.assertNotEqual(threading.get_ident(), main, name)
                touched.append(name)
                return function(*args, **kwargs)
            return call
        process = FakeProcess()
        def spawn(*args, **kwargs):
            mailbox.publish(args[0][-1], 'result.json', {'ok': True, 'value': []})
            return process
        with mock.patch.object(client.tempfile, 'mkdtemp', side_effect=off_thread('tempfile', tempfile.mkdtemp)), \
             mock.patch.object(client.os, 'stat', side_effect=off_thread('stat', os.stat)), \
             mock.patch.object(client.mailbox, 'publish', side_effect=off_thread('publish', mailbox.publish)), \
             mock.patch.object(client.mailbox, 'take', side_effect=off_thread('take', mailbox.take)), \
             mock.patch.object(client.subprocess, 'Popen', side_effect=off_thread('spawn', spawn)), \
             mock.patch.object(client.shutil, 'rmtree', side_effect=off_thread('cleanup', client.shutil.rmtree)):
            job = client.Job('tasks')
            job.done()  # A fast worker may already have replied; either state is valid.
            self.assertTrue(job._finished.wait(2))
            self.assertEqual(job.result(), [])
            job.close()
            client.close_all()
            self.assertTrue(job._cleaned.wait(2))
        self.assertTrue({'tempfile', 'stat', 'publish', 'take', 'spawn', 'cleanup'}.issubset(touched))

    def test_cancel_during_spawn_cannot_leak_helper_and_close_all_does_not_wait(self):
        started, release = threading.Event(), threading.Event()
        process = FakeProcess()
        def spawn(*args, **kwargs):
            started.set()
            if not release.wait(3):
                raise RuntimeError('Fixture gate was not released')
            return process
        with mock.patch.object(client.subprocess, 'Popen', side_effect=spawn):
            job = client.Job('tasks')
            self.assertTrue(started.wait(2))
            before = time.monotonic()
            client.close_all()
            self.assertLess(time.monotonic() - before, .1)
            self.assertTrue(job.done())
            self.assertFalse(job._cleaned.is_set())
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                job.result()
            release.set()
            self.assertTrue(job._cleaned.wait(2))
        self.assertEqual(process.kills, 1)

    def test_stale_hwnd_pid_thread_process_and_class_never_execute(self):
        user = mock.Mock()
        expected = (123, 456, '987654', 'FixtureClass')
        for current in (None, (124, *expected[1:]), (123, 457, *expected[2:]),
                        (123, 456, '987655', expected[3]), (123, 456, expected[2], 'OtherClass')):
            with mock.patch.object(native_windows, '_api', return_value=user), \
                 mock.patch.object(native_windows, '_identity', return_value=current):
                with self.assertRaises(RuntimeError):
                    native_windows.act('100', expected[0], identity=expected[1:])
        user.ShowWindowAsync.assert_not_called()
        user.SetForegroundWindow.assert_not_called()
        with mock.patch.object(native_windows, '_api', return_value=user):
            for identity in (None, (456, '', 'FixtureClass'), (True, '987654', 'FixtureClass')):
                with self.assertRaises(ValueError):
                    native_windows.act('100', expected[0], identity=identity)
        user.ShowWindowAsync.assert_not_called()

    def test_identity_is_rechecked_before_action(self):
        user = mock.Mock()
        expected = (123, 456, '987654', 'FixtureClass')
        with mock.patch.object(native_windows, '_api', return_value=user), \
             mock.patch.object(native_windows, '_identity', side_effect=[expected, None]):
            with self.assertRaises(RuntimeError):
                native_windows.act('100', 123, identity=expected[1:])
        user.ShowWindowAsync.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows enumeration')
    def test_real_task_enumeration_is_read_only_and_bounded(self):
        rows = native_windows.tasks()
        self.assertLessEqual(len(rows), 256)
        client._validate_value('tasks', rows)
        for row in rows:
            self.assertEqual(row['actionable'], bool(row['process_started']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
