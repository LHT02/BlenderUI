# SPDX-License-Identifier: GPL-2.0-or-later
"""Run with bundled Python; operates only in uniquely created fixture folders."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "modules"))
from blui_explorer import file_tasks, shell_client


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
