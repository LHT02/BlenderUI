# SPDX-License-Identifier: GPL-2.0-or-later
"""Folder-panel synchronization/schema, without bpy or any user-file operations."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import folder_panel_model as panels, model


def row(name, folder=False):
    return {'path': 'D:\\fixture\\' + name, 'name': name, 'folder': folder}


class FolderPanels(unittest.TestCase):
    def test_manual_stale_cards_are_kept_and_managed_ones_removed(self):
        existing = [{'id': 'old', 'path': row('old')['path'], 'managed': True},
                    {'id': 'manual', 'path': row('manual')['path'], 'managed': False}]
        plan = panels.changes(existing, [row('new')], 0)
        self.assertEqual(plan['remove'], ['old'])
        self.assertEqual(plan['add'], [row('new')])
        self.assertFalse(plan['truncated'])

    def test_case_equivalent_manual_reference_prevents_duplicate(self):
        existing = [{'id': 'manual', 'path': 'd:/FIXTURE/A.TXT', 'managed': False}]
        plan = panels.changes(existing, [row('a.txt')], 100)
        self.assertEqual(plan['add'], [])
        self.assertEqual(plan['remove'], [])

    def test_truncated_snapshot_does_not_prove_managed_reference_deleted(self):
        existing = [{'id': 'keep', 'path': row('not in partial list')['path'], 'managed': True}]
        plan = panels.changes(existing, [row('new')], 0, complete=False)
        self.assertEqual(plan['remove'], [])
        self.assertEqual(plan['add'], [])
        self.assertTrue(plan['truncated'])

    def test_managed_metadata_updates_do_not_recreate_identity(self):
        existing = [{'id': 'keep', 'path': row('A.txt')['path'], 'managed': True}]
        plan = panels.changes(existing, [row('a.txt', True), row('b.txt')], 0)
        self.assertEqual(plan['update'], [('keep', row('a.txt', True))])
        self.assertEqual(plan['add'], [])
        self.assertTrue(plan['truncated'])

    def test_bad_and_relative_directories_rejected(self):
        for path in ('relative', '', None, 'D:\\bad\x00path', 'x' * 32769):
            with self.subTest(path=path), self.assertRaises(ValueError):
                panels.directory(path)

    def test_native_frame_directory_color_and_source_roundtrip(self):
        payload = {'version': 2, 'directory': '', 'nodes': [
            {'kind': model.FRAME, 'id': 'a' * 32, 'location': [0, 0],
             'props': {'folder_path': 'D:\\fixture', 'color': [.1, .2, .3], 'use_custom_color': True}},
            {'kind': model.FILE, 'id': 'b' * 32, 'parent': 'a' * 32, 'location': [0, 0],
             'props': {'portal_owner': 'a' * 32}, **row('A.txt')}]}
        clean = model.validate(payload)
        self.assertEqual(model.validate(clean), clean)
        self.assertEqual(clean['nodes'][0]['props']['folder_path'], 'D:\\fixture')
        self.assertEqual(clean['nodes'][1]['props']['portal_owner'], 'a' * 32)

    def test_invalid_panel_colors_rejected(self):
        for color in ([1, 2, 3], [float('nan'), 0, 0], [True, 0, 0], 'rgb', [0, 1]):
            payload = {'version': 2, 'directory': '', 'nodes': [
                {'kind': model.FRAME, 'location': [0, 0], 'props': {'color': color}}]}
            with self.subTest(color=color), self.assertRaises(ValueError):
                model.validate(payload)


if __name__ == '__main__':
    unittest.main()
