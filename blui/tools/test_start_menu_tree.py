# SPDX-License-Identifier: GPL-2.0-or-later
"""Classic Start menu presentation regressions; no bpy, filesystem or launches."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import start_menu_model as schema, start_menu_tree as tree


def app(relative, source='user'):
    return {'id': schema.app_id(source, relative), 'relative': relative, 'source': source,
            'name': Path(relative.replace('\\', '/')).stem, 'path': 'C:\\Programs\\' + relative,
            'group': ''}


class ProgramTreeTests(unittest.TestCase):
    def test_folders_first_and_root_apps_alphabetical(self):
        rows = [app('Zulu.lnk'), app('Tools\\Calc.lnk'), app('Alpha.lnk')]
        items = tree.programs(rows)
        self.assertEqual([(item['kind'], item['name']) for item in items],
                         [('FOLDER', 'Tools'), ('APP', 'Alpha'), ('APP', 'Zulu')])
        self.assertEqual({item['app_id'] for item in items if item['kind'] == 'APP'},
                         {rows[0]['id'], rows[2]['id']})

    def test_user_and_common_merge_folder_but_keep_launch_identities(self):
        rows = [app('Tools\\One.lnk'), app('tools\\Two.lnk', 'common'),
                app('Tools\\One.lnk', 'common')]
        collapsed = tree.programs(rows)
        self.assertEqual(len(collapsed), 1)
        items = tree.programs(rows, [collapsed[0]['folder_id']])
        self.assertTrue(items[0]['expanded'])
        self.assertEqual(len(items), 4)
        self.assertEqual({item['app_id'] for item in items[1:]}, {row['id'] for row in rows})
        self.assertTrue(all(item['depth'] == 1 for item in items[1:]))

    def test_nested_expansion_is_local_and_parent_collapse_preserves_children_state(self):
        rows = [app('Tools\\More\\One.lnk'), app('Other\\Two.lnk')]
        tools = tree.folder_key(['Tools'])
        more = tree.folder_key(['Tools', 'More'])
        opened = tree.programs(rows, [tools, more])
        self.assertEqual([(item['name'], item['depth']) for item in opened],
                         [('Other', 0), ('Tools', 0), ('More', 1), ('One', 2)])
        self.assertEqual(len(tree.programs(rows, [more])), 2)
        self.assertEqual(tree.programs(rows, [more, tools]), opened)

    def test_folder_identity_is_unicode_normalized_and_ignores_display_group_text(self):
        self.assertEqual(tree.folder_key(['ＴＯＯＬＳ']), tree.folder_key(['tools']))
        row = app('Folder name - Tools\\One.lnk')
        row['group'] = 'Not / The / Actual / Path'
        self.assertEqual(tree.programs([row])[0]['name'], 'Folder name - Tools')

    def test_removed_and_stale_opened_folder_does_not_invent_app(self):
        items = tree.programs([app('One.lnk')], [tree.folder_key(['Removed'])])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], 'One')

    def test_budget_depth_and_folder_keys_are_bounded(self):
        with self.assertRaises(ValueError):
            tree.programs([app('One.lnk')] * (schema.MAX_APPS + 1))
        with self.assertRaises(ValueError):
            tree.programs([app('\\'.join(['depth'] * 9 + ['One.lnk']))])
        with self.assertRaises(ValueError):
            tree.programs([app('One.lnk')], ['arbitrary path'])

    def test_home_preserves_pin_order_recent_order_and_removes_duplicates(self):
        a, b, c = app('A.lnk'), app('B.lnk'), app('C.lnk')
        items = tree.home([a, b, c], [b['id'], a['id']], [b['id'], c['id']])
        self.assertEqual([item['name'] for item in items],
                         ['Pinned Apps', 'B', 'A', 'Recently Opened Apps', 'C'])
        self.assertEqual(len({item['app_id'] for item in items if item['kind'] == 'APP'}), 3)

    def test_fresh_profile_gets_bounded_useful_programs(self):
        rows = [app(str(index) + '.lnk') for index in range(100)]
        self.assertEqual(len(tree.home(rows, [], [])), 13)
        self.assertEqual(len(tree.home([], [], [])), 0)

    def test_search_reaches_collapsed_folder_apps_and_is_not_a_command(self):
        calc = app('Tools\\Calculator.lnk')
        value = {'rows': [calc], 'pins': [], 'recent': []}
        self.assertEqual(tree.contents(value, 'ALL')[0]['kind'], 'FOLDER')
        found = tree.contents(value, 'ALL', 'calculator')
        self.assertEqual(found[0]['app_id'], calc['id'])
        self.assertEqual(found[0]['depth'], 0)
        self.assertEqual(tree.contents(value, 'ALL', 'calculator && shutdown /s'), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
