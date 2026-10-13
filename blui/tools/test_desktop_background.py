# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded wallpaper math, IPC and native isolated decode tests; no Blender/UI required."""
import base64
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import background as bg


def png_rgba(width, height, raw):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    scan = b''.join(b'\0' + raw[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(scan)) + chunk(b'IEND', b''))


class BackgroundTest(unittest.TestCase):
    def test_fit_and_center(self):
        self.assertEqual(bg.placements((200, 100), (100, 100), 'FIT'),
                         [((0, 25, 100, 75), (0, 0, 1, 1))])
        self.assertEqual(bg.placements((50, 20), (100, 100), 'CENTER'),
                         [((25, 40, 75, 60), (0, 0, 1, 1))])

    def test_fill_crops_not_distorts(self):
        self.assertEqual(bg.placements((200, 100), (100, 100), 'FILL'),
                         [((0, 0, 100, 100), (.25, 0, .75, 1))])
        self.assertEqual(bg.placements((200, 100), (100, 100), 'FILL', 1),
                         [((0, 0, 100, 100), (.5, 0, 1, 1))])

    def test_alignment(self):
        self.assertEqual(bg.placements((50, 20), (100, 100), 'CENTER', -1, 1),
                         [((0, 80, 50, 100), (0, 0, 1, 1))])

    def test_stretch(self):
        self.assertEqual(bg.placements((7, 900), (100, 50), 'STRETCH'),
                         [((0, 0, 100, 50), (0, 0, 1, 1))])

    def test_tile_clips_and_bounded(self):
        rows = bg.placements((30, 30), (100, 100), 'TILE')
        self.assertLessEqual(len(rows), 25)
        self.assertAlmostEqual(sum((r[2] - r[0]) * (r[3] - r[1]) for r, uv in rows), 10000)
        rows = bg.placements((1, 1), (16000, 16000), 'TILE')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], (0, 0, 16000, 16000))
        self.assertEqual(rows[0][1][2] - rows[0][1][0], 16000)

    def test_two_monitors_negative_origin_mixed_dpi(self):
        # Different local region/DPI sizes retain one continuous physical wallpaper.
        first = bg.placements((3000, 1000), (1500, 1000), 'SPAN',
                              virtual_rect=(-1000, -100, 2000, 900), monitor_rect=(-1000, -100, 0, 900))
        second = bg.placements((3000, 1000), (1000, 500), 'SPAN',
                               virtual_rect=(-1000, -100, 2000, 900), monitor_rect=(0, -100, 2000, 900))
        self.assertEqual(first, [((0, 0, 1500, 1000), (0, 0, 1 / 3, 1))])
        self.assertEqual(second, [((0, 0, 1000, 500), (1 / 3, 0, 1, 1))])

    def test_vertical_span_origin(self):
        rows = bg.placements((1000, 2000), (500, 500), 'SPAN',
                             virtual_rect=(0, -1000, 1000, 1000), monitor_rect=(0, -1000, 1000, 0))
        self.assertEqual(rows, [((0, 0, 500, 500), (0, .5, 1, 1))])

    def test_span_missing_monitor_falls_back(self):
        self.assertEqual(bg.placements((10, 10), (100, 100), 'SPAN'),
                         bg.placements((10, 10), (100, 100), 'FILL'))

    def test_invalid_settings(self):
        for value in ({'opacity': float('nan')}, {'opacity': True}, {'enabled': 1},
                      {'align_x': 2}, {'path': 'a\0b'}, {'fit': []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bg.validate_settings(value)

    def test_invalid_dimensions(self):
        for size in ((0, 1), (True, 10), (float('inf'), 10), (1e9, 10)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                bg.placements(size, (100, 100))

    def test_invalid_monitor_geometry(self):
        with self.assertRaises(ValueError):
            bg.placements((10, 10), (10, 10), 'SPAN', virtual_rect=(0, 0, 10, 10),
                          monitor_rect=(5, 5, 20, 20))

    def test_pixels_size_and_alpha(self):
        raw = bytes((255, 0, 0, 0, 10, 20, 30, 128))
        value = {'path': 'picture.png', 'width': 2, 'height': 1,
                 'source_width': 2, 'source_height': 1,
                 'rgba_zlib': base64.b64encode(zlib.compress(raw)).decode()}
        self.assertEqual(bg.validate_pixels(value, decompress=True), raw)
        value['rgba_zlib'] = base64.b64encode(zlib.compress(raw + b'!')).decode()
        with self.assertRaises(ValueError):
            bg.validate_pixels(value)

    def test_decompression_bomb_and_trailing_stream(self):
        value = {'path': 'a.png', 'width': 1, 'height': 1, 'source_width': 1, 'source_height': 1}
        for compressed in (zlib.compress(b'x' * 100000), zlib.compress(b'1234') + b'ignored', b'invalid'):
            value['rgba_zlib'] = base64.b64encode(compressed).decode()
            with self.subTest(compressed=compressed[:20]), self.assertRaises((ValueError, zlib.error)):
                bg.validate_pixels(value)

    def test_source_header_limits(self):
        with tempfile.TemporaryDirectory(prefix='blui_wallpaper_test_') as directory:
            path = Path(directory) / 'image.png'
            path.write_bytes(png_rgba(2, 2, b'\0' * 16))
            self.assertEqual(bg._header(path), (2, 2))
            path.write_bytes(png_rgba(32768, 32768, b''))
            with self.assertRaises(ValueError):
                bg._header(path)
            path.write_bytes(b'not an image')
            with self.assertRaises(ValueError):
                bg._header(path)

    @unittest.skipUnless(os.name == 'nt', 'Native image decoder requires Windows')
    def test_native_png_alpha_channels_orientation(self):
        raw = bytes((255, 0, 0, 255, 0, 255, 0, 128,
                     0, 0, 255, 64, 0, 0, 0, 0))
        with tempfile.TemporaryDirectory(prefix='blui_wallpaper_test_') as directory:
            path = Path(directory) / 'transparent.png'
            path.write_bytes(png_rgba(2, 2, raw))
            value = bg.inspect(str(path))
            self.assertEqual((value['width'], value['height']), (2, 2))
            self.assertEqual(bg.validate_pixels(value, decompress=True), raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
