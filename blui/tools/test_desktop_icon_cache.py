# SPDX-License-Identifier: GPL-2.0-or-later
"""Both native PreviewImage slots must contain pixels for taskbar/menu and canvas icons."""
import base64
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))


class Collection(dict):
    def new(self, name):
        value = SimpleNamespace(icon_id=len(self) + 1)
        self[name] = value
        return value


class IconCache(unittest.TestCase):
    def setUp(self):
        previews = ModuleType('bpy.utils.previews')
        previews.new, previews.remove = Collection, lambda _value: None
        bpy, utils = ModuleType('bpy'), ModuleType('bpy.utils')
        bpy.utils, utils.previews = utils, previews
        spec = importlib.util.spec_from_file_location('blui_desktop._icon_cache_test',
            SOURCE / 'scripts/modules/blui_desktop/icon_cache.py')
        self.cache = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {'bpy': bpy, 'bpy.utils': utils, 'bpy.utils.previews': previews}):
            spec.loader.exec_module(self.cache)
        self.addCleanup(self.cache.close)

    def test_small_operator_and_large_canvas_slots_have_identical_once_flipped_pixels(self):
        pixels = bytes([255, 0, 0, 255, 0, 0, 255, 128])
        self.cache.apply([{'path': 'C:\\fixture\\app.exe', 'width': 1, 'height': 2,
                           'rgba': base64.b64encode(pixels).decode('ascii')}])
        image = next(iter(self.cache._previews.values()))
        self.assertEqual(image.icon_size, (1, 2))
        self.assertEqual(image.image_size, image.icon_size)
        self.assertEqual(image.icon_pixels_float, image.image_pixels_float)
        self.assertEqual(image.icon_pixels_float[:4], [0, 0, 1, 128 / 255])
        self.assertEqual(sum(self.cache._unique.values()), 4)

    def test_equal_bytes_with_different_dimensions_do_not_share_icon_identity(self):
        pixels = base64.b64encode(bytes([255, 0, 0, 255] * 4)).decode('ascii')
        self.cache.apply([{'path': path, 'width': width, 'height': height, 'rgba': pixels}
                          for path, width, height in (('one', 1, 4), ('two', 2, 2))])
        self.assertNotEqual(self.cache.value('one'), self.cache.value('two'))


if __name__ == '__main__':
    unittest.main()
