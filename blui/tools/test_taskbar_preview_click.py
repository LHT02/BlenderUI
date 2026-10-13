# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the actual preview-pick method via AST, without bpy or Win32 writes."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop.taskbar_previews import _source


def row(handle, *, pid=10, thread=20, started='30', name='GHOST_WindowClass'):
    return {'handle': str(handle), 'pid': pid, 'thread_id': thread,
            'process_started': started, 'window_class': name, 'title': 'QA ' + str(handle)}


class PreviewClickTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.c = row(101), row(102), row(103)
        self.activate, self.close = mock.Mock(), mock.Mock()
        self.group = {'tasks': [self.a, self.b]}
        self.namespace = {'_geometry': {'card_rects': [(0, 0, 100, 100), (100, 0, 200, 100)]},
            '_targets': (_source(self.a), _source(self.b)), '_source': _source, 'close': self.close,
            'taskbar_windows': SimpleNamespace(menu_state=lambda _window: {'key': 'qa', 'device': 'QA'}),
            'taskbar_actions': SimpleNamespace(find_group=lambda *_args, **_kwargs: self.group,
                                               activate=self.activate)}
        source = Path(__file__).resolve().parents[2] / 'scripts/modules/blui_desktop/shell_hover.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'WM_OT_blui_preview_pick')
        method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == 'invoke')
        extracted = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(extracted)
        exec(compile(extracted, str(source), 'exec'), self.namespace)
        self.context = SimpleNamespace(window=SimpleNamespace(height=100))

    def click_second(self):
        return self.namespace['invoke'](None, self.context, SimpleNamespace(mouse_x=150, mouse_y=50))

    def test_replaced_second_card_cannot_activate_different_live_app_window(self):
        self.group['tasks'] = [self.c, self.a]
        self.assertEqual(self.click_second(), {'CANCELLED'})
        self.activate.assert_not_called()
        self.close.assert_called_once()

    def test_reordered_group_still_activates_displayed_second_card_b(self):
        self.group['tasks'] = [self.b, self.a]
        self.assertEqual(self.click_second(), {'FINISHED'})
        self.activate.assert_called_once_with(self.b)
        self.close.assert_called_once()

    def test_shortened_group_never_indexes_missing_new_second_task(self):
        self.group['tasks'] = [self.a]
        self.assertEqual(self.click_second(), {'CANCELLED'})
        self.activate.assert_not_called()

    def test_same_hwnd_with_new_process_creation_identity_is_not_displayed_b(self):
        self.group['tasks'] = [self.a, row(102, started='31')]
        self.assertEqual(self.click_second(), {'CANCELLED'})
        self.activate.assert_not_called()

    def test_same_hwnd_but_changed_pid_thread_or_class_is_not_displayed_b(self):
        for kwargs in ({'pid': 11}, {'thread': 21}, {'name': 'AnotherWindowClass'}):
            with self.subTest(**kwargs):
                self.group['tasks'] = [self.a, row(102, **kwargs)]
                self.assertEqual(self.click_second(), {'CANCELLED'})
        self.activate.assert_not_called()

    def test_visible_slot_without_valid_original_identity_never_activates(self):
        self.namespace['_targets'] = (_source(self.a), None)
        self.assertEqual(self.click_second(), {'CANCELLED'})
        self.activate.assert_not_called()

    def test_slot_count_changed_without_target_token_never_indexes_out_of_bounds(self):
        self.namespace['_targets'] = (_source(self.a),)
        self.assertEqual(self.click_second(), {'CANCELLED'})
        self.activate.assert_not_called()

    def test_group_disappeared_closes_preview_without_activation(self):
        self.group = None
        self.assertEqual(self.click_second(), {'CANCELLED'})
        self.activate.assert_not_called()
        self.close.assert_called_once()

    def test_outside_cards_never_activates_any_source(self):
        result = self.namespace['invoke'](None, self.context, SimpleNamespace(mouse_x=250, mouse_y=50))
        self.assertEqual(result, {'CANCELLED'})
        self.activate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
