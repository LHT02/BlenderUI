# SPDX-License-Identifier: GPL-2.0-or-later
"""A real image paint viewport must not inherit mesh UV wires, even from old settings."""
import os
from pathlib import Path
import tempfile
import time
import sys
import bpy
from bl_ui import space_filebrowser_shell

root = Path(tempfile.mkdtemp(prefix='blui_paint_overlay_'))
state = {'step': 0, 'started': time.monotonic()}


def override():
    return bpy.context.temp_override(window=state['window'], area=state['area'], region=state['region'])


def capture(name):
    with override():
        bpy.ops.screen.screenshot(filepath=str(root / (name + '.png')))


def step():
    if time.monotonic() - state['started'] > 25:
        raise TimeoutError('Paint overlay regression timed out')
    n = state['step']
    if n == 0:
        space_filebrowser_shell.unregister()
        window = bpy.context.window_manager.windows[0]
        area = next(iter(window.screen.areas))
        area.type = 'IMAGE_EDITOR'
        region = next(r for r in area.regions if r.type == 'WINDOW')
        state.update(window=window, area=area, region=region)
        with override():
            model = next(obj for obj in bpy.context.scene.objects if obj.type == 'MESH')
            bpy.context.view_layer.objects.active = model
            assert model.data.uv_layers, 'Factory fixture has no UV map'
            if model.mode != 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.image.new(name='paint-overlay-fixture', width=256, height=256, color=(0, 0, 0, 1))
            area.spaces.active.mode = 'PAINT'
            area.spaces.active.overlay.show_overlays = True
            area.spaces.active.uv_editor.show_texpaint = False
            bpy.ops.image.view_all(fit_view=True)
        delay = 0.5
    elif n == 1:
        capture('without-wire-setting')
        state['area'].spaces.active.uv_editor.show_texpaint = True
        state['area'].tag_redraw()
        delay = 0.5
    elif n == 2:
        capture('legacy-wire-setting')
        delay = 0.2
    else:
        baseline = bpy.data.images.load(str(root / 'without-wire-setting.png'))
        legacy = bpy.data.images.load(str(root / 'legacy-wire-setting.png'))
        assert baseline.size[:] == legacy.size[:]
        width, height = baseline.size[:]
        # Compare central image content, excluding headers, toolbars and image borders.
        first, second = list(baseline.pixels), list(legacy.pixels)
        region = state['region']
        changes = 0
        for y in range(max(0, region.y + region.height // 4), min(height, region.y + 3 * region.height // 4)):
            for x in range(max(0, region.x + region.width // 4), min(width, region.x + 3 * region.width // 4)):
                index = (y * width + x) * 4
                changes += any(abs(first[index + channel] - second[index + channel]) > 0.02 for channel in range(3))
        assert changes == 0, 'Mesh UV shadows leaked into image paint: %d pixels' % changes
        print('PASS Paint viewport has no mesh UV wireframe with legacy show_texpaint enabled', flush=True)
        print('check_image_paint_overlay: PASS', root, flush=True)
        os._exit(0)
    state['step'] += 1
    return delay


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=0.5)
