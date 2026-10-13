# SPDX-License-Identifier: GPL-2.0-or-later
"""Proof that owned native shell windows actually paint content, not only correct RNA sizes."""
from pathlib import Path
import bpy


def verify(window, label, *, large_taskbar_icons=False):
    assert label in {'taskbar', 'start-menu', 'chooser'}
    path = Path('D:/BlenderUI/build') / ('shell-' + label + '.png')
    area = window.screen.areas[0]
    with bpy.context.temp_override(window=window, area=area):
        assert bpy.ops.screen.screenshot(filepath=str(path)) == {'FINISHED'}
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = image.size
        colors = set()
        for y in range(1, height - 1, max(1, height // 64)):
            for x in range(1, width - 1, max(1, width // 128)):
                offset = 4 * (y * width + x)
                colors.add(tuple(round(channel * 255) for channel in image.pixels[offset:offset + 3]))
        assert len(colors) > 8, (label, 'blank shell render', len(colors))
        if large_taskbar_icons:
            # The fixture has exactly one verified BLUI executable group. Its
            # colored cached icon must really grow, not just its button/backdrop.
            rgba = list(image.pixels)
            colored = []
            for y in range(height):
                for x in range(width // 4, 3 * width // 4):
                    offset = 4 * (y * width + x)
                    rgb = rgba[offset:offset + 3]
                    if max(rgb) > .4 and max(rgb) - min(rgb) > .2:
                        colored.append((x, y))
            assert colored, 'cached taskbar application icon did not paint'
            bounds = (min(x for x, y in colored), min(y for x, y in colored),
                      max(x for x, y in colored), max(y for x, y in colored))
            scale = bpy.context.preferences.system.ui_scale
            assert bounds[2] - bounds[0] + 1 >= round(22 * scale), ('small taskbar glyph', bounds, scale)
            assert bounds[1] >= 3 and bounds[3] < height - 3, ('clipped taskbar glyph', bounds, height)
            print('LARGE_TASKBAR_ICON', bounds, 'UI_SCALE', scale, flush=True)
        print('SHELL_DRAW', label, width, height, len(colors), str(path), flush=True)
        if large_taskbar_icons:
            return bounds
    finally:
        bpy.data.images.remove(image)
