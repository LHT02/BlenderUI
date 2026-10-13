# SPDX-License-Identifier: GPL-2.0-or-later
"""Responsive Start sizing and exact-parent context-child lifetime checks."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import start_menu_layout as layout


class MetricsTests(unittest.TestCase):
    def test_default_rows_and_right_gap(self):
        value = layout.metrics(620, 1)
        self.assertEqual(value['rows'], 21)
        self.assertEqual(value['row_scale'], 1.5)
        self.assertGreater(value['spacer_units'], 0)
        self.assertFalse(value['hidden'])

    def test_window_scaled_with_dpi_keeps_same_logical_layout(self):
        for scale in (.5, 1, 1.25, 1.5, 2, 3):
            self.assertEqual(layout.metrics(620 * scale, scale), layout.metrics(620, 1))

    def test_small_screen_clamping_reduces_rows_not_text_size(self):
        value = layout.metrics(960, 2)
        self.assertEqual(value['rows'], 15)
        self.assertFalse(value['hidden'])
        self.assertLess(value['spacer_units'], layout.metrics(620, 1)['spacer_units'])
        self.assertLessEqual(value['rows'] * 20 + 166, 480)

    def test_compact_screen_folds_secondary_locations(self):
        value = layout.metrics(640, 2)
        self.assertEqual(value['rows'], 7)
        self.assertEqual(value['row_scale'], 1)
        self.assertEqual(value['hidden'], {'MUSIC', 'DOWNLOADS'})

    def test_tiny_screen_keeps_essential_links_and_bounded_gap(self):
        value = layout.metrics(420, 2)
        self.assertEqual(value['rows'], 2)
        self.assertEqual(value['user_scale'], 1)
        self.assertNotIn('FILES', value['hidden'])
        self.assertNotIn('COMPUTER', value['hidden'])
        self.assertNotIn('SETTINGS', value['hidden'])
        self.assertGreaterEqual(value['spacer_units'], 0)

    def test_empty_result_notice_has_reserved_space(self):
        self.assertEqual(layout.metrics(960, 2, empty=True)['rows'], 14)

    def test_zero_and_extreme_sizes_remain_bounded(self):
        self.assertEqual(layout.metrics(0, 1)['rows'], 1)
        self.assertEqual(layout.metrics(1e308, 1e-300)['rows'], 21)

    def test_invalid_dimensions_rejected(self):
        for height in (True, -1, None, '620', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                layout.metrics(height, 1)
        for scale in (True, 0, -1, None, '1', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                layout.metrics(620, scale)


class ContextChildTests(unittest.TestCase):
    def test_only_matching_live_start_app_child_keeps_parent(self):
        child = SimpleNamespace(blui_shell_role='TASK_CHOOSER')
        token = (123, '456')
        self.assertTrue(layout.owns_context_child(token, [child],
            lambda _window: {'kind': 'START_APP', 'source': token}))
        self.assertTrue(layout.owns_context_child(token, [child],
            lambda _window: {'kind': 'START_APP', 'source': list(token)}))
        self.assertFalse(layout.owns_context_child(token, [],
            lambda _window: {'kind': 'START_APP', 'source': token}))

    def test_other_parent_or_role_or_menu_cannot_suppress_focus_close(self):
        token = (123, '456')
        child = SimpleNamespace(blui_shell_role='TASK_CHOOSER')
        for state in ({'kind': 'SETTINGS', 'source': token},
                      {'kind': 'START_APP', 'source': (124, '456')},
                      {'kind': 'START_APP', 'source': (123, '457')},
                      {'kind': 'START_APP', 'source': '123456'},
                      {'kind': 'START_APP'}):
            with self.subTest(state=state):
                self.assertFalse(layout.owns_context_child(token, [child], lambda _window: state))
        normal = SimpleNamespace(blui_shell_role='NORMAL')
        self.assertFalse(layout.owns_context_child(token, [normal],
            lambda _window: {'kind': 'START_APP', 'source': token}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
