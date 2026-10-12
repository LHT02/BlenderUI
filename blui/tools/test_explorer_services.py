# SPDX-License-Identifier: GPL-2.0-or-later
"""Run with bundled Python; operates only in uniquely created fixture folders."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "modules"))
from blui_explorer import file_tasks, shell_client, mailbox


class Messages(unittest.TestCase):
    def test_transient_windows_file_lock(self):
        with tempfile.TemporaryDirectory(prefix='blui_mailbox_') as directory:
            mailbox.publish(directory, 'reply.json', {'items': [1]})
            target = Path(directory) / 'reply.json'
            with mock.patch.object(Path, 'read_text', side_effect=PermissionError):
                self.assertIsNone(mailbox.take(directory, 'reply.json'))
            self.assertTrue(target.exists())
            with mock.patch.object(Path, 'unlink', side_effect=PermissionError):
                self.assertIsNone(mailbox.take(directory, 'reply.json'))
            self.assertTrue(target.exists())
            self.assertEqual(mailbox.take(directory, 'reply.json'), {'items': [1]})
            self.assertIsNone(mailbox.take(directory, 'reply.json'))


class Files(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="blui_explorer_test_")
        self.root = Path(self.temp.name)
        self.source = self.root / "源文件.txt"
        self.source.write_text("fixture 中文", encoding="utf-8")
        self.target = self.root / "destination"
        self.target.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_copy_and_move(self):
        copied = file_tasks.transfer([str(self.source)], str(self.target))[0]
        self.assertEqual(Path(copied).read_text(encoding="utf-8"), "fixture 中文")
        self.assertTrue(self.source.exists())
        with self.assertRaises(FileExistsError):
            file_tasks.transfer([str(self.source)], str(self.target), True)
        self.assertTrue(self.source.exists())
        destination = self.root / "moved"
        destination.mkdir()
        moved = file_tasks.transfer([copied], str(destination), True)[0]
        self.assertFalse(Path(copied).exists())
        self.assertTrue(Path(moved).exists())

    def test_folder_copy_and_descendant_rejection(self):
        folder = self.root / "folder"
        nested = folder / "child"
        nested.mkdir(parents=True)
        (nested / "data.txt").write_text("inside", encoding="utf-8")
        with self.assertRaises(ValueError):
            file_tasks.transfer([str(folder)], str(nested))
        file_tasks.transfer([str(folder)], str(self.target))
        self.assertEqual((self.target / "folder/child/data.txt").read_text(), "inside")

    def test_archives_and_traversal(self):
        output = self.root / "test.zip"
        file_tasks.archive([str(self.source)], str(output))
        extracted = self.root / "extract"
        file_tasks.extract_zip(output, extracted)
        self.assertEqual((extracted / self.source.name).read_bytes(), self.source.read_bytes())
        bad = self.root / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("../escaped.txt", "bad")
        with self.assertRaises(ValueError):
            file_tasks.extract_zip(bad, self.root / "unsafe")
        self.assertFalse((self.root / "escaped.txt").exists())
        self.assertFalse((self.root / "unsafe").exists())

    def test_7z(self):
        if not file_tasks.seven_zip():
            self.skipTest("7-Zip not installed")
        output = self.root / "test.7z"
        file_tasks.archive([str(self.source)], str(output), "7Z")
        self.assertEqual(output.read_bytes()[:6], b"7z\xbc\xaf\x27\x1c")

    def test_windows_names(self):
        for name in ("../oops", "CON.txt", "a:b", "trailing.", ""):
            with self.assertRaises(ValueError):
                file_tasks.valid_name(name)
        self.assertEqual(file_tasks.valid_name("中文.txt"), "中文.txt")


class IsolatedShell(unittest.TestCase):
    def drain(self, session, limit=12):
        started = time.monotonic()
        while session.pending:
            before = time.monotonic()
            session.poll()
            self.assertLess(time.monotonic() - before, .2, 'Folder polling blocked the UI')
            self.assertLess(time.monotonic() - started, limit)
            time.sleep(.01)

    def test_folder_real_scopes_and_reuse(self):
        from blui_explorer.shell_folder_client import FolderSession
        with tempfile.TemporaryDirectory(prefix='blui_folder_menu_') as directory:
            paths = [str(Path(directory) / name) for name in ('one', 'two')]
            for path in paths:
                Path(path).mkdir()
            helper = FolderSession(paths[:1])
            try:
                self.drain(helper)
                self.assertFalse(helper.errors, helper.errors)
                self.assertTrue(all(not child.errors for child in helper.helpers.values()),
                                {scope: child.errors for scope, child in helper.helpers.items()})
                pids = [child.process.pid for child in helper.helpers.values()]
                self.assertEqual(len(set(pids)), 2)
                commands = [row['id'] for row in helper.items['root'] if row['id'] and not row.get('submenu')]
                self.assertEqual(len(commands), len(set(commands)))
                self.assertFalse(any(row.get('localize') for row in helper.items['root']))
                for row in helper.items['root']:
                    if row['label'] in {'7-Zip', 'TortoiseSVN'} and row.get('submenu'):
                        helper.request('expand', node=row['submenu'])
                        self.drain(helper)
                        self.assertNotIn(row['submenu'], helper.errors, helper.errors)
                        self.assertTrue(helper.items.get(row['submenu']), helper.helpers['folder'].errors)
                token = helper.token
                helper.reset(paths[1:])
                self.drain(helper)
                self.assertNotEqual(token, helper.token)
                self.assertEqual(pids, [child.process.pid for child in helper.helpers.values()])
                helper.request('invoke', command=commands[0])
                helper.poll()
                self.assertIn('does not belong', helper.errors['invoke'])
                print('Folder menus: two scopes, distinct IDs, real delayed submenus, warm reuse OK')
            finally:
                helper.close()

    def test_folder_scope_routing_and_partial_failure(self):
        from blui_explorer.shell_folder_client import FolderSession
        worker = str(Path(__file__).parent / 'fixtures/shell_worker_scopes.py')
        helper = FolderSession(['fixture'], workers={'folder': worker, 'directory': worker})
        try:
            self.drain(helper)
            commands = {row['label']: row['id'] for row in helper.items['root'] if not row.get('submenu')}
            self.assertNotEqual(commands['folder'], commands['directory'])
            helper.request('invoke', command=commands['directory'])
            self.drain(helper)
            self.assertEqual(helper.errors['invoke'], 'directory:1')
            self.assertNotIn('invoke', helper.helpers['folder'].errors)
        finally:
            helper.close()
        stalled = str(Path(__file__).parent / 'fixtures/shell_worker_stall.py')
        helper = FolderSession(['fixture'], timeout=.5, workers={'folder': worker, 'directory': stalled})
        try:
            self.drain(helper)
            self.assertNotIn('root', helper.errors, 'One slow scope hid all healthy commands')
            self.assertTrue(any(row['enabled'] for row in helper.items['root']))
            self.assertTrue(any(row.get('localize') and not row.get('loading') for row in helper.items['root']))
        finally:
            helper.close()

    def wait(self, session, node="root", limit=12):
        start = time.monotonic()
        while node not in session.items and node not in session.errors:
            before = time.monotonic()
            session.poll()
            self.assertLess(time.monotonic() - before, 0.2, "poll blocked the UI thread")
            self.assertLess(time.monotonic() - start, limit)
            time.sleep(0.01)

    def test_timeout_does_not_block_client(self):
        worker = Path(__file__).parent / "fixtures/shell_worker_stall.py"
        session = shell_client.Session(["fixture"], worker=str(worker), timeout=0.25)
        try:
            self.wait(session, limit=2)
            self.assertIn("timed out", session.errors["root"])
            session.process.wait(timeout=2)
        finally:
            session.close()

    def test_crash_does_not_crash_client(self):
        worker = Path(__file__).parent / "fixtures/shell_worker_crash.py"
        session = shell_client.Session(["fixture"], worker=str(worker))
        try:
            self.wait(session)
            self.assertIn("exited", session.errors["root"])
        finally:
            session.close()

    def test_full_pipe_does_not_block_client(self):
        worker = Path(__file__).parent / "fixtures/shell_worker_no_read.py"
        before = time.monotonic()
        session = shell_client.Session(["fixture" * 100000], worker=str(worker), timeout=0.25)
        try:
            self.assertLess(time.monotonic() - before, 0.5)
            self.wait(session, limit=2)
            self.assertIn("timed out", session.errors["root"])
        finally:
            session.close()

    def test_real_shell_and_delayed_submenus(self):
        session = shell_client.Session([os.path.join(os.environ["WINDIR"], "System32/notepad.exe")])
        try:
            self.wait(session)
            self.assertNotIn("root", session.errors)
            items = session.items["root"]
            self.assertTrue(any(item.get("id") for item in items))
            session.request('status')
            self.wait(session, 'status')
            self.assertFalse(session.items['status'], 'An idle menu host unexpectedly owns a visible dialog')
            for label in ("7-Zip", "TortoiseSVN"):
                item = next((item for item in items if item["label"] == label), None)
                if item is None:
                    continue  # Extensions are machine-specific.
                session.request("expand", node=item["submenu"])
                self.wait(session, item["submenu"])
                self.assertNotIn(item["submenu"], session.errors)
                self.assertTrue(session.items[item["submenu"]], label + " submenu is empty")
                print(label, "items:", len(session.items[item["submenu"]]))
            session.request("invoke", command=999999)
            self.wait(session, "invoke")
            self.assertIn("does not belong", session.errors["invoke"])
        finally:
            session.close()

    def test_idle_host_reuse_invalidates_old_commands(self):
        worker = Path(__file__).parent / 'fixtures/shell_worker_delayed.py'
        helpers = [shell_client.Session(['fixture-%d' % i], worker=str(worker)) for i in range(3)]
        try:
            for helper in helpers:
                shell_client.sessions[helper.token] = helper
                self.wait(helper)
            old = helpers[0]
            token, pid, command = old.token, old.process.pid, old.items['root'][0]['id']
            reused = shell_client.get_session(['new-selection'])
            self.assertIs(reused, old)
            self.assertEqual(reused.process.pid, pid)
            self.assertNotEqual(reused.token, token)
            self.assertNotIn(token, shell_client.sessions)
            self.wait(reused)
            self.assertNotEqual(reused.items['root'][0]['id'], command)
            reused.request('invoke', command=command)
            self.wait(reused, 'invoke')
            self.assertIn('does not belong', reused.errors['invoke'])
            reused.request('status')
            self.wait(reused, 'status')
            self.assertFalse(reused.invoked, 'Completed dialog-free commands left the host permanently busy')
        finally:
            shell_client.close_all()


if __name__ == "__main__":
    unittest.main(verbosity=2)
