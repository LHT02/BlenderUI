# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Shift+P creates native frames without moving desktop file references.

Run serially: BLUI.exe --factory-startup --enable-event-simulate
    --python-exit-code 1 --python <this_file.py>
Set BLUI_QA_KEYCONFIG to Blender, Blender_27x or Industry_Compatible.
Only this process's window and private temporary fixture are used. No real file
action, desktop persistence, OS cursor, taskbar or user CONFIG is changed.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import bpy
from bl_ui import space_filebrowser_shell
from blui_desktop import groups, model, runtime, serialization, session
from blui_desktop.types import canvas

fixture = tempfile.TemporaryDirectory(prefix='blui_frame_shortcut_')
folder = Path(fixture.name)
state = {'phase': 0, 'started': time.monotonic()}
session.disable_for_tests = True


def window():
    # Native Undo replaces Main/RNA: retain only identities, never old wrappers.
    result = next((item for item in bpy.context.window_manager.windows
                   if item.blui_native_handle == state['handle']), None)
    assert result, 'Owned QA window disappeared'
    return result


def root():
    result = bpy.data.node_groups.get(state['tree_name'])
    assert result and result.bl_idname == model.TREE, 'Undo lost the desktop tree'
    return result


def area():
    result = next((item for item in window().screen.areas
                   if item.type == 'NODE_EDITOR' and item.spaces.active.node_tree == root()), None)
    assert result, 'Owned desktop editor disappeared'
    return result


def region():
    return next(item for item in area().regions if item.type == 'WINDOW')


def context():
    return bpy.context.temp_override(window=window(), area=area(), region=region())


def edited():
    space = area().spaces.active
    return space.edit_tree or space.node_tree


def cards(tree):
    return {item.label: item for item in tree.nodes if item.bl_idname == model.FILE}


def world_position(node):
    x, y = node.location
    parent = node.parent
    while parent:
        x, y = x + parent.location.x, y + parent.location.y
        parent = parent.parent
    return x, y


def positions(tree):
    return {name: world_position(node) for name, node in cards(tree).items()}


def assert_positions(tree, expected):
    actual = positions(tree)
    assert actual.keys() == expected.keys(), (actual, expected)
    for name, xy in actual.items():
        assert all(abs(xy[axis] - expected[name][axis]) < .01 for axis in (0, 1)), (
            'Frame changed visible position', name, xy, expected[name])


def select(tree, labels):
    for node in tree.nodes:
        node.select = node.bl_idname == model.FILE and node.label in labels
    tree.nodes.active = next((node for node in tree.nodes if node.select), None)


def shortcut():
    target = region()
    x, y = target.x + target.width // 2, target.y + target.height // 2
    # Route genuine input through the active preset/addon maps, not the Python operator.
    window().event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    for kind, value, shift in (('LEFT_SHIFT', 'PRESS', True), ('P', 'PRESS', True),
                               ('P', 'RELEASE', True), ('LEFT_SHIFT', 'RELEASE', False)):
        window().event_simulate(type=kind, value=value, x=x, y=y,
                                ctrl=False, alt=False, shift=shift, oskey=False)


def assert_frame(tree, selected, expected):
    frames = [node for node in tree.nodes if node.bl_idname == model.FRAME]
    assert len(frames) == 1, ('Shift+P did not create exactly one native frame', len(frames))
    frame = frames[0]
    assert serialization.valid_id(frame.get('blui_id')), 'Frame lacks portable identity'
    assert frame.label, 'Frame lacks display label'
    for name, node in cards(tree).items():
        assert node.parent == (frame if name in selected else None), (name, node.parent)
    assert_positions(tree, expected)
    assert not window().blui_has_modal_interaction, 'Shift+P left a modal operation active'


def roundtrip(tree, name):
    # Exercise the actual portable schema, JSON on disk, and native parent reconstruction.
    payload = serialization.snapshot(tree)
    path = folder / (name + '.json')
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    loaded = model.validate(json.loads(path.read_text(encoding='utf-8')))
    clone = bpy.data.node_groups.new('Frame Shortcut Roundtrip QA', model.TREE)
    serialization.apply(clone, loaded)
    assert serialization.snapshot(clone) == payload, 'Saved frame/parent graph did not roundtrip'
    bpy.data.node_groups.remove(clone)


def advance(delay=.3):
    state['phase'] += 1
    return delay


def step():
    if time.monotonic() - state['started'] > 35:
        raise TimeoutError('Shift+P desktop frame regression timed out')
    phase = state['phase']
    if phase == 0:
        preset = os.environ.get('BLUI_QA_KEYCONFIG', 'Blender')
        assert preset in {'Blender', 'Blender_27x', 'Industry_Compatible'}
        path = Path(bpy.utils.resource_path('LOCAL')) / 'scripts/presets/keyconfig' / (preset + '.py')
        assert bpy.ops.preferences.keyconfig_activate(filepath=str(path)) == {'FINISHED'}
        print('FRAME_SHORTCUT_PRESET', preset, flush=True)
        space_filebrowser_shell.unregister()
        if bpy.app.timers.is_registered(runtime.tick):
            bpy.app.timers.unregister(runtime.tick)
        runtime.cancel_pending()
        own_window = bpy.context.window_manager.windows[0]
        state['handle'] = own_window.blui_native_handle
        editor = max(own_window.screen.areas, key=lambda item: item.width * item.height)
        editor.type = 'NODE_EDITOR'
        space = editor.spaces.active
        space.tree_type = model.TREE
        tree = bpy.data.node_groups.new('Frame Shortcut Desktop QA', model.TREE)
        tree.use_fake_user = True
        state['tree_name'] = tree.name
        space.node_tree, space.pin = tree, True
        space.show_region_ui = space.show_region_toolbar = False
        for index, name in enumerate(('A', 'B', 'C')):
            file = folder / (name + '.txt')
            file.write_text('owned frame fixture ' + name, encoding='utf-8')
            node = tree.nodes.new(model.FILE)
            node.filepath, node.label = str(file), name
            node.location = (index * 280 - 200, index * -80 + 160)
        active = own_window.view_layer.objects.active
        if active and active.mode != 'OBJECT':
            with context():
                assert bpy.ops.object.mode_set(mode='OBJECT') == {'FINISHED'}
        bpy.context.preferences.edit.use_global_undo = True
        select(tree, {'A', 'B'})
        with context():
            assert bpy.ops.wm.blui_canvas_frame_selected.poll()
            bpy.ops.node.view_all()
            bpy.ops.ed.undo_push(message='Shift+P QA original cards')
        return advance(.5)
    if phase == 1:
        if any(node.dimensions.x <= 0 for node in root().nodes):
            return .1
        state['root_positions'] = positions(root())
        shortcut()
        return advance(.4)
    if phase == 2:
        assert_frame(root(), {'A', 'B'}, state['root_positions'])
        roundtrip(root(), 'root-frame')
        print('PASS actual Shift+P frames selected A/B, leaves C outside, keeps visible positions and roundtrips',
              flush=True)
        with context():
            assert bpy.ops.ed.undo() == {'FINISHED'}
        return advance(.4)
    if phase == 3:
        assert not any(node.bl_idname == model.FRAME for node in root().nodes)
        assert all(node.parent is None for node in cards(root()).values())
        assert_positions(root(), state['root_positions'])
        assert not window().blui_has_modal_interaction
        print('PASS native Undo removes the new frame and restores original file-card parents', flush=True)
        select(root(), set())
        with context():
            assert not bpy.ops.wm.blui_canvas_frame_selected.poll()
        shortcut()
        return advance(.3)
    if phase == 4:
        assert not any(node.bl_idname == model.FRAME for node in root().nodes)
        assert not window().blui_has_modal_interaction
        assert_positions(root(), state['root_positions'])
        print('PASS empty selection does not create a frame or retain a modal', flush=True)
        select(root(), {'A', 'B'})
        with context():
            assert bpy.ops.node.group_make('EXEC_DEFAULT', True) == {'FINISHED'}
        return advance(.4)
    if phase == 5:
        group = next(node for node in root().nodes if node.bl_idname == groups.GROUP)
        assert group.node_tree and group.node_tree.bl_idname == model.TREE
        if edited() == root():
            group.select = True
            root().nodes.active = group
            with context():
                assert bpy.ops.node.group_edit(exit=False) == {'FINISHED'}
        assert edited() == group.node_tree, 'Native group entry did not expose the child edit_tree'
        with context():
            assert canvas(bpy.context) == group.node_tree
        select(edited(), {'A', 'B'})
        state['group_positions'] = positions(edited())
        with context():
            bpy.ops.node.view_all()
            bpy.ops.ed.undo_push(message='Shift+P QA unframed group cards')
        return advance(.4)
    if phase == 6:
        shortcut()
        return advance(.4)
    if phase == 7:
        group = next(node for node in root().nodes if node.bl_idname == groups.GROUP)
        assert_frame(group.node_tree, {'A', 'B'}, state['group_positions'])
        assert not any(node.bl_idname == model.FRAME for node in root().nodes), 'Framed root instead of edit_tree'
        assert cards(root())['C'].parent is None
        roundtrip(root(), 'group-frame')
        print('PASS actual Shift+P frames inside a native group edit_tree and saves its child parents', flush=True)
        with context():
            assert bpy.ops.ed.undo() == {'FINISHED'}
        return advance(.4)
    if phase == 8:
        group = next(node for node in root().nodes if node.bl_idname == groups.GROUP)
        assert not any(node.bl_idname == model.FRAME for node in group.node_tree.nodes)
        assert all(node.parent is None for node in cards(group.node_tree).values())
        assert_positions(group.node_tree, state['group_positions'])
        assert cards(root())['C'].parent is None
        assert not window().blui_has_modal_interaction
        for name in ('A', 'B', 'C'):
            assert (folder / (name + '.txt')).read_text(encoding='utf-8') == 'owned frame fixture ' + name
        runtime.cancel_pending()
        fixture.cleanup()
        print('check_canvas_frame_shortcut: PASS (real key events, native parenting, JSON, Undo, group edit)',
              flush=True)
        sys.stdout.flush()
        os._exit(0)


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        print('FRAME_SHORTCUT_DIAGNOSTIC phase', state['phase'], flush=True)
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.5)
