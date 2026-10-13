# SPDX-License-Identifier: GPL-2.0-or-later
"""Native preview protocol and RAM-only cache regressions; no GUI or user-file mutation."""
import base64
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
from blui_desktop import thumbnails


def row(path='C:\\private\\a.png', width=1, height=2, rgba=None):
    rgba = bytes((255, 0, 0, 255, 0, 0, 255, 128)) if rgba is None else rgba
    return {'path': path, 'width': width, 'height': height,
            'rgba': base64.b64encode(rgba).decode('ascii')}


class ThumbnailProtocol(unittest.TestCase):
    def test_candidates_use_only_strings_and_cover_browser_families(self):
        with mock.patch('os.stat', side_effect=AssertionError('UI stat')), mock.patch('builtins.open', side_effect=AssertionError('UI open')):
            for name in ('a.PNG', 'b.mp4', 'c.blend', 'd.blend12', 'e.blend.gz', 'f.ttf', 'g.woff2', 'asset.blend/Object/Cube'):
                self.assertTrue(thumbnails.candidate('C:\\private\\' + name), name)
            for name in ('a.lnk', 'b.exe', 'c.txt', 'd.png.exe'):
                self.assertFalse(thumbnails.candidate('C:\\private\\' + name), name)
            self.assertFalse(thumbnails.candidate('C:\\private\\folder.png', True))
            self.assertFalse(thumbnails.candidate('relative.png'))

    def test_protocol_preserves_non_square_top_down_rgba(self):
        pixels = bytes((255, 0, 0, 255, 0, 0, 255, 128))
        self.assertEqual(thumbnails.decode_reply(struct.pack('<4sII', b'BTP1', 1, 2) + pixels), (1, 2, pixels))

    def test_protocol_rejects_bad_dimensions_magic_size_and_trailing_data(self):
        for data in (b'', struct.pack('<4sII', b'ICON', 1, 1) + bytes(4),
                     struct.pack('<4sII', b'BTP1', 0, 1) + bytes(4),
                     struct.pack('<4sII', b'BTP1', 257, 1) + bytes(1028),
                     struct.pack('<4sII', b'BTP1', 1, 1) + bytes(3),
                     struct.pack('<4sII', b'BTP1', 1, 1) + bytes(5)):
            with self.assertRaises(ValueError):
                thumbnails.decode_reply(data)

    def test_rows_reject_empty_half_zero_types_encoding_or_surplus(self):
        good = row()
        thumbnails.validate_pixels([good, thumbnails.empty('C:\\private\\b.jpg')])
        for changed in ({'path': ''}, {'width': True}, {'width': 257}, {'height': 0},
                        {'rgba': '*'}, {'rgba': ''}, {'surplus': 1}):
            with self.assertRaises(ValueError):
                thumbnails.validate_pixels([dict(good, **changed)])
        with self.assertRaises(ValueError):
            thumbnails.validate_pixels([good] * 3)

    def test_extract_rejects_invalid_batches_before_process_creation(self):
        with mock.patch.object(thumbnails.subprocess, 'run') as launch:
            for paths in ([], ['C:\\a.png'] * 3, ['a.png'], ['C:\\bad\x00.png'], [42]):
                with self.assertRaises(ValueError):
                    thumbnails.extract(paths)
            launch.assert_not_called()

    def test_unsupported_shortcuts_are_never_previewed(self):
        with mock.patch.object(thumbnails.subprocess, 'run') as launch:
            self.assertEqual(thumbnails.extract(['C:\\private\\app.lnk']), [thumbnails.empty('C:\\private\\app.lnk')])
            launch.assert_not_called()

    def test_crash_and_timeout_return_bounded_fallback(self):
        for outcome in (SimpleNamespace(returncode=11), subprocess.TimeoutExpired('owned preview', 3.5)):
            args = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
            with mock.patch.object(thumbnails.subprocess, 'run', **args):
                self.assertEqual(thumbnails.extract(['C:\\private\\bad.png']), [thumbnails.empty('C:\\private\\bad.png')])

    def test_success_launches_private_early_mode_without_shell_and_cleans_reply(self):
        replies = []
        rgba = bytes((255, 0, 0, 255, 0, 0, 255, 128))
        def launch(arguments, **options):
            self.assertEqual(arguments[1:3], ['--blui-file-preview', 'C:\\private\\a.png'])
            self.assertEqual(options['timeout'], 3.5)
            self.assertNotIn('shell', options)
            path = Path(arguments[3])
            replies.append(path)
            path.write_bytes(struct.pack('<4sII', b'BTP1', 1, 2) + rgba)
            return SimpleNamespace(returncode=0)
        with mock.patch.object(thumbnails.subprocess, 'run', side_effect=launch):
            self.assertEqual(thumbnails.extract(['C:\\private\\a.png']), [row()])
        self.assertFalse(replies[0].parent.exists())


class Collection(dict):
    counter = 0

    def new(self, name):
        Collection.counter += 1
        preview = SimpleNamespace(icon_id=Collection.counter, image_size=None, image_pixels_float=None)
        self[name] = preview
        return preview


class ThumbnailCache(unittest.TestCase):
    def setUp(self):
        previews = ModuleType('bpy.utils.previews')
        previews.new, previews.remove = Collection, lambda unused: None
        utils, bpy = ModuleType('bpy.utils'), ModuleType('bpy')
        utils.previews, bpy.utils = previews, utils
        spec = importlib.util.spec_from_file_location('blui_desktop._thumbnail_cache_test',
            SOURCE / 'scripts/modules/blui_desktop/thumbnail_cache.py')
        self.cache = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {'bpy': bpy, 'bpy.utils': utils, 'bpy.utils.previews': previews}):
            spec.loader.exec_module(self.cache)

    def tearDown(self):
        self.cache.close()

    def test_value_pending_and_cancel_are_ram_only_and_deduplicated(self):
        with mock.patch('os.stat', side_effect=AssertionError('UI stat')), mock.patch('builtins.open', side_effect=AssertionError('UI open')), mock.patch('subprocess.run', side_effect=AssertionError('UI subprocess')):
            for unused in range(8):
                self.assertEqual(self.cache.value('C:\\private\\a.png'), 0)
            self.assertEqual(self.cache.pending(), ['C:\\private\\a.png'])
            self.assertEqual(self.cache.pending(), [])
            self.cache.cancel_pending()
            self.cache.value('C:\\private\\a.png')
            self.assertEqual(self.cache.pending(), ['C:\\private\\a.png'])

    def test_apply_flips_rgba_once_and_deduplicates_identical_images(self):
        self.cache.apply([row(), row('C:\\private\\b.png')])
        self.assertEqual(self.cache.value('C:\\private\\a.png'), self.cache.value('C:\\private\\b.png'))
        self.assertEqual(len(self.cache._unique), 1)
        preview = next(iter(self.cache._previews.values()))
        self.assertEqual(preview.image_size, (1, 2))
        self.assertEqual(preview.image_pixels_float[:4], [0, 0, 1, 128 / 255])
        self.assertEqual(preview.image_pixels_float[4:], [1, 0, 0, 1])

    def test_dimensions_are_part_of_dedup_identity(self):
        self.cache.apply([row(), row('C:\\private\\b.png', 2, 1)])
        self.assertEqual(len(self.cache._unique), 2)

    def test_refresh_keeps_old_preview_until_reply_then_replaces(self):
        with mock.patch.object(self.cache.time, 'monotonic', return_value=0):
            self.cache.apply([row()])
            old = self.cache.value('C:\\private\\a.png')
        with mock.patch.object(self.cache.time, 'monotonic', return_value=61):
            self.assertEqual(self.cache.value('C:\\private\\a.png'), old)
            self.assertEqual(self.cache.pending(), ['C:\\private\\a.png'])
            self.cache.apply([row(rgba=bytes(8))])
            self.assertNotEqual(self.cache.value('C:\\private\\a.png'), old)
            self.assertEqual(len(self.cache._unique), 1)

    def test_timeout_does_not_stick_loading_and_has_retry_cooldown(self):
        path = 'C:\\private\\a.png'
        with mock.patch.object(self.cache.time, 'monotonic', return_value=0):
            self.cache.value(path)
            self.cache.fail(self.cache.pending())
            self.assertEqual(self.cache.value(path), 0)
            self.assertEqual(self.cache.pending(), [])
        with mock.patch.object(self.cache.time, 'monotonic', return_value=121):
            self.cache.value(path)
            self.assertEqual(self.cache.pending(), [path])

    def test_fail_keeps_previous_preview_but_native_no_preview_clears_it(self):
        path = 'C:\\private\\a.png'
        self.cache.apply([row(path)])
        old = self.cache.value(path)
        self.cache.fail([path])
        self.assertEqual(self.cache.value(path), old)
        self.cache.apply([thumbnails.empty(path)])
        self.assertEqual(self.cache.value(path), 0)
        self.assertEqual(len(self.cache._unique), 0)

    def test_admission_retry_restores_batch_without_duplicate_loading(self):
        for suffix in ('a.png', 'b.png', 'c.png'):
            self.cache.value('C:\\private\\' + suffix)
        batch = self.cache.pending()
        self.assertEqual(len(batch), 2)
        self.cache.retry(batch)
        all_paths = self.cache.pending() + self.cache.pending()
        self.assertEqual(len(all_paths), 3)
        self.assertEqual(len(set(all_paths)), 3)

    def test_queue_entry_and_pixel_budgets_are_bounded(self):
        self.cache.MAX_ENTRIES = 3
        for index in range(10):
            self.cache.value('C:\\private\\' + str(index) + '.png')
        self.assertEqual(len(self.cache._queued), 3)
        self.cache.MAX_PIXELS = 1
        self.cache.apply([row()])
        self.assertEqual(len(self.cache._unique), 0)
        self.assertEqual(len(self.cache._entries), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
