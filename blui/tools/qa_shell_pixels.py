# SPDX-License-Identifier: GPL-2.0-or-later
"""Proof that owned native shell windows actually paint content, not only correct RNA sizes."""
from pathlib import Path
import bpy


def verify(window, label):
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
        print('SHELL_DRAW', label, width, height, len(colors), str(path), flush=True)
    finally:
        bpy.data.images.remove(image)
