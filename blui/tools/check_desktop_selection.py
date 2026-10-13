# SPDX-License-Identifier: GPL-2.0-or-later
"""Real desktop box gestures must finish on release and cancel without edits.

BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python this_file.py
Only this process's native window and owned temporary references are used.
No OS cursor, clipboard, system taskbar or user layout/config is changed.
"""
import os
from pathlib import Path
import sys
import tempfile
import time

import bpy
from blui_desktop import model, runtime, session
from bl_ui import space_filebrowser_shell

fixture = tempfile.TemporaryDirectory(prefix='blui_box_selection_')
state = {'phase': 0, 'started': time.monotonic()}
session.disable_for_tests = True


def region():
    return next(r for r in state['area'].regions if r.type == 'WINDOW')


def context():
    return bpy.context.temp_override(window=state['window'], area=state['area'], region=region())


def event(kind, value, point=None, *, shift=False):
    x, y = point or state['start']
    state['window'].event_simulate(type=kind, value=value, x=round(x), y=round(y),
                                   ctrl=False, shift=shift, alt=False, oskey=False)


def move(point):
    event('MOUSEMOVE', 'NOTHING', point)


def selection():
    return {node.label for node in state['tree'].nodes if node.select}


def bounds(node):
    area_region = region()
    scale = node.dimensions.x / node.width
    x, y = node.location.x * scale, node.location.y * scale
    corners = ((x, y), (x + node.dimensions.x, y - node.dimensions.y))
    return [tuple(value + origin for value, origin in zip(
        area_region.view2d.view_to_region(*corner, clip=False), (area_region.x, area_region.y)))
        for corner in corners]


def check_released(label, selected):
    assert not state['window'].blui_has_modal_interaction, label + ': gesture did not finish'
    assert selection() == selected, (label, selection(), selected)
    print('PASS ' + label, flush=True)


def step():
    if time.monotonic() - state['started'] > 30:
        raise TimeoutError('Desktop box-selection regression timed out')
    phase = state['phase']
    if phase == 0:
        preset = os.environ.get('BLUI_QA_KEYCONFIG', 'Blender')
        assert preset in {'Blender', 'Blender_27x', 'Industry_Compatible'}
        path = Path(bpy.utils.resource_path('LOCAL')) / 'scripts/presets/keyconfig' / (preset + '.py')
        assert bpy.ops.preferences.keyconfig_activate(filepath=str(path)) == {'FINISHED'}
        print('SELECTION_PRESET', preset, flush=True)
        space_filebrowser_shell.unregister()
        if bpy.app.timers.is_registered(runtime.tick):
            bpy.app.timers.unregister(runtime.tick)
        runtime.cancel_pending()
        state['window'] = bpy.context.window_manager.windows[0]
        area = max(state['window'].screen.areas, key=lambda a: a.width * a.height)
        state['area'] = area
        area.type = 'NODE_EDITOR'
        space = area.spaces.active
        space.tree_type = model.TREE
        tree = bpy.data.node_groups.new('Desktop Box Selection QA', model.TREE)
        state['tree'] = tree
        space.node_tree, space.pin = tree, True
        space.show_region_ui = space.show_region_toolbar = False
        for index, name in enumerate(('A', 'B', 'C')):
            path = Path(fixture.name) / (name + '.txt')
            path.write_text('owned selection fixture', encoding='utf-8')
            node = tree.nodes.new(model.FILE)
            node.filepath, node.label = str(path), name
            node.location, node.select = (index * 280, 0), False
        return advance(.4)
    if phase == 1:
        if any(node.dimensions.x <= 0 for node in state['tree'].nodes):
            return .1
        with context():
            bpy.ops.node.view_all()
        return advance(.4)
    if phase == 2:
        a, b, _c = [next(n for n in state['tree'].nodes if n.label == name) for name in ('A', 'B', 'C')]
        at, ab = bounds(a)
        bt, bb = bounds(b)
        state['start'] = (at[0] - 16, at[1] + 16)
        state['end'] = (bb[0] + 16, min(ab[1], bb[1]) - 16)
        for point in (state['start'], state['end']):
            assert region().x < point[0] < region().x + region().width
            assert region().y < point[1] < region().y + region().height
        move(state['start'])
        event('LEFTMOUSE', 'PRESS')
        mid = tuple((a + b) / 2 for a, b in zip(state['start'], state['end']))
        move(mid)
        return advance(.25)
    if phase == 3:
        move(state['end'])
        return advance(.2)
    if phase == 4:
        assert state['window'].blui_has_modal_interaction, 'Empty-space drag did not enter native box selection'
        event('LEFTMOUSE', 'RELEASE', state['end'])
        return advance(.3)
    if phase == 5:
        check_released('empty-space box ends on left release and selects A/B only', {'A', 'B'})
        move(state['start'])
        event('B', 'PRESS')
        event('B', 'RELEASE')
        return advance(.2)
    if phase == 6:
        event('LEFTMOUSE', 'PRESS')
        move(state['end'])
        return advance(.2)
    if phase == 7:
        event('LEFTMOUSE', 'RELEASE', state['end'])
        return advance(.3)
    if phase == 8:
        check_released('B-key box ends on release', {'A', 'B'})
        move(state['start'])
        event('B', 'PRESS')
        event('B', 'RELEASE')
        return advance(.2)
    if phase == 9:
        event('LEFTMOUSE', 'PRESS')
        move(state['end'])
        event('ESC', 'PRESS', state['end'])
        event('ESC', 'RELEASE', state['end'])
        return advance(.3)
    if phase == 10:
        check_released('Escape cancels box and preserves selection', {'A', 'B'})
        move(state['start'])
        event('B', 'PRESS')
        event('B', 'RELEASE')
        return advance(.2)
    if phase == 11:
        event('RIGHTMOUSE', 'PRESS')
        event('RIGHTMOUSE', 'RELEASE')
        return advance(.3)
    if phase == 12:
        check_released('right-click cancels waiting box', {'A', 'B'})
        # Modifier release is consumed by the gesture map rather than opening a menu.
        move(state['start'])
        event('B', 'PRESS')
        event('B', 'RELEASE')
        return advance(.2)
    if phase == 13:
        event('LEFTMOUSE', 'PRESS', shift=True)
        move(state['end'])
        return advance(.2)
    if phase == 14:
        event('LEFTMOUSE', 'RELEASE', state['end'], shift=True)
        return advance(.3)
    if phase == 15:
        check_released('B-key Shift subtract box releases and deselects', set())
        with context():
            assert bpy.ops.node.select_circle('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
        return advance(.2)
    if phase == 16:
        assert state['window'].blui_has_modal_interaction
        event('ESC', 'PRESS')
        event('ESC', 'RELEASE')
        return advance(.2)
    if phase == 17:
        check_released('native circle selection also cancels on Escape', set())
        print('check_desktop_selection: PASS', flush=True)
        fixture.cleanup()
        os._exit(0)


def advance(delay):
    state['phase'] += 1
    return delay


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        window = state.get('window')
        print('SELECTION_DIAGNOSTIC', state['phase'], selection() if state.get('tree') else None,
              window.blui_has_modal_interaction if window else None, flush=True)
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.5)
