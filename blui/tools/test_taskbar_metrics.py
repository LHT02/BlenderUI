# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure taskbar sizing checks; no bpy imports or native window mutations."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import taskbar_metrics as metrics


class TaskbarMetricsTests(unittest.TestCase):
    def test_logical_dimensions_allow_real_32_pixel_icon(self):
        self.assertEqual(metrics.BAR_HEIGHT, 56)
        self.assertEqual(metrics.BUTTON_SIZE, 40)
        self.assertEqual(metrics.BUTTON_SIZE - 2 * 4, 32)
        self.assertGreater(metrics.BAR_HEIGHT, metrics.BUTTON_SIZE)

    def test_capacity_reserves_sides_start_and_overflow(self):
        self.assertEqual(metrics.icon_capacity(672, 1), 10)
        self.assertEqual(metrics.icon_capacity(671, 1), 9)
        self.assertEqual(metrics.icon_capacity(312, 1), 1)

    def test_dpi_scaling_keeps_same_logical_capacity(self):
        for scale in (0.5, 1, 1.25, 1.5, 2, 3):
            self.assertEqual(metrics.icon_capacity(672 * scale, scale), 10)

    def test_narrow_regions_keep_a_single_application_slot(self):
        for width in (0, 1, 80, 200, 272):
            self.assertEqual(metrics.icon_capacity(width, 1), 1)

    def test_large_display_never_exceeds_group_limit(self):
        self.assertEqual(metrics.icon_capacity(100000, 1), metrics.MAX_ICONS)
        self.assertEqual(metrics.icon_capacity(1e308, 1e-300), metrics.MAX_ICONS)

    def test_invalid_width_rejected(self):
        for width in (-1, True, None, '672', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                metrics.icon_capacity(width, 1)

    def test_invalid_scale_rejected(self):
        for scale in (0, -1, True, None, '1', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                metrics.icon_capacity(672, scale)


if __name__ == '__main__':
    unittest.main(verbosity=2)
