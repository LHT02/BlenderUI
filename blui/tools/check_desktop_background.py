# SPDX-License-Identifier: GPL-2.0-or-later
"""Native wallpaper rendering QA in one own disposable BLUI instance.

Run after build with --factory-startup --python-exit-code 1 --python this file.
Never changes user layouts, windows or desktop background settings.
"""
import base64
import os
from pathlib import Path
import sys
import zlib
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_desktop_background import png_rgba
from blui_desktop import background

_state = 0
_tree = None
_area = None
_previous_tree = None


def fail(error):
    import traceback
    traceback.print_exc()
    print('DESKTOP_BACKGROUND FAIL:', str(error), flush=True)
    os._exit(1)


def run():
    global _state, _tree, _area
    try:
        if _state == 0:
            _area = max(bpy.context.screen.areas, key=lambda area: area.width * area.height)
            _area.type = 'NODE_EDITOR'
            _area.spaces.active.tree_type = 'BLUIDesktopTree'
            _tree = bpy.data.node_groups.new('Wallpaper QA', 'BLUIDesktopTree')
            _tree.service_identity = 'wallpaper-own-test'
            _area.spaces.active.node_tree = _tree
            _area.spaces.active.pin = True
            # Pure RAM test pixels: solid red/green above semi-transparent blue/clear.
            pixels = bytes((255, 0, 0, 255, 0, 255, 0, 255,
                            0, 0, 255, 128, 0, 0, 0, 0))
            response = {'path': 'wallpaper-qa.png', 'width': 2, 'height': 2,
                        'source_width': 2, 'source_height': 2,
                        'rgba_zlib': base64.b64encode(zlib.compress(pixels)).decode()}
            background.apply(_tree, response)
            _tree.background_fit = 'STRETCH'
            card = _tree.nodes.new('BLUIDesktopFile')
            card.label = 'Native node remains above wallpaper'
            card.location = (-200, 100)
            background.register()
            _area.tag_redraw()
            _state += 1
            return .5
        if _state == 1:
            result = background.diagnostics(_tree)
            assert result and result['draw_count'] > 0 and not result['error'], result
            _tree.background_fit = 'TILE'
            _area.tag_redraw()
            _state += 1
            return .5
        if _state == 2:
            result = background.diagnostics(_tree)
            assert result['draw_count'] > 1 and not result['error'], result
            _tree.background_fit = 'SPAN'
            _tree.monitor = 'right'
            background.unregister()
            background.register(lambda: {'coordinate_space': 'physical', 'monitors': [
                {'device': 'left', 'rect': [-1920, 0, 0, 1080]},
                {'device': 'right', 'rect': [0, 0, 2560, 1440]}]})
            pixels = b'\x10\x30\x60\x80' * 4
            background.apply(_tree, {'path': 'span-qa.png', 'width': 2, 'height': 2,
                                    'source_width': 2, 'source_height': 2,
                                    'rgba_zlib': base64.b64encode(zlib.compress(pixels)).decode()})
            _area.tag_redraw()
            _state += 1
            return .5
        result = background.diagnostics(_tree)
        assert result and result['draw_count'] and not result['error'], result
        path = Path(__file__).resolve().parents[3] / 'build' / 'desktop-background.png'
        # This screenshot is an own QA artifact, not the user's OS desktop.
        with bpy.context.temp_override(area=_area):
            bpy.ops.screen.screenshot(filepath=str(path))
        print('DESKTOP_BACKGROUND PASS: PRE_VIEW, transparency, native nodes, tile, negative-origin span', flush=True)
        os._exit(0)
    except Exception as error:
        fail(error)


bpy.app.timers.register(run, first_interval=.5)
