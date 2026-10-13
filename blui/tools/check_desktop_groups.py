# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual native desktop group make/edit/ungroup, references and shared layout DAG.

Run sequentially with other GUI fixtures, using the main agent's freshly built
BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python this_file.py.
Only this fixture's temporary files are created; no real file action is invoked.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import bpy
from blui_desktop import groups, model, runtime
from blui_desktop.types import canvas

fixture = Path(tempfile.mkdtemp(prefix='blui_desktop_groups_'))
file_a, file_b = fixture / 'a.txt', fixture / 'b.txt'
file_a.write_text('group fixture a', encoding='utf-8')
file_b.write_text('group fixture b', encoding='utf-8')
state = {'phase': 0, 'started': time.monotonic()}


def override():
    window, area = state['window'], state['area']
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=area, region=region)


def root():
    return state['area'].spaces.active.node_tree


def reference_rows(tree):
    return {node.filepath: tuple(node.location) for _owner, node in groups.file_nodes(tree)}


def key(kind, modifier=None):
    window = state['window']
    area = state['area']
    region = next(region for region in area.regions if region.type == 'WINDOW')
    point = (region.x + region.width // 2, region.y + region.height // 2)
    flags = {'ctrl': modifier == 'LEFT_CTRL', 'alt': modifier == 'LEFT_ALT', 'shift': modifier == 'LEFT_SHIFT'}
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=point[0], y=point[1])
    if modifier:
        window.event_simulate(type=modifier, value='PRESS', x=point[0], y=point[1], **flags)
    window.event_simulate(type=kind, value='PRESS', x=point[0], y=point[1], **flags)
    window.event_simulate(type=kind, value='RELEASE', x=point[0], y=point[1], **flags)
    if modifier:
        window.event_simulate(type=modifier, value='RELEASE', x=point[0], y=point[1])


def diagnostic():
    with override():
        space = bpy.context.space_data
        print('GROUP_CONTEXT', {'area': bpy.context.area.type, 'tree_type': space.tree_type,
            'root': space.node_tree.name if space.node_tree else None,
            'edit': space.edit_tree.name if space.edit_tree else None,
            'make_poll': bpy.ops.node.group_make.poll(), 'edit_poll': bpy.ops.node.group_edit.poll(),
            'ungroup_poll': bpy.ops.node.group_ungroup.poll(),
            'modal': state['window'].blui_has_modal_interaction,
            'selected': [(node.bl_idname, node.name) for node in space.edit_tree.nodes if node.select]
                        if space.edit_tree else []}, flush=True)
        for config in bpy.context.window_manager.keyconfigs:
            km = config.keymaps.get('Node Editor')
            if km:
                print('GROUP_KEYMAP', config.name, [(item.idname, item.type, item.value,
                    item.ctrl, item.alt, item.shift, item.active) for item in km.keymap_items
                    if item.idname in {'node.group_make', 'node.group_edit', 'node.group_ungroup'}], flush=True)


def step():
    if time.monotonic() - state['started'] > 30:
        raise TimeoutError('Desktop group regression timed out')
    phase = state['phase']
    if phase == 0:
        if bpy.app.timers.is_registered(runtime.tick):
            bpy.app.timers.unregister(runtime.tick)
        runtime.cancel_pending()
        state['window'] = bpy.context.window_manager.windows[0]
        state['area'] = max(state['window'].screen.areas, key=lambda area: area.width * area.height)
        area = state['area']
        area.type = 'NODE_EDITOR'
        space = area.spaces.active
        space.tree_type = model.TREE
        tree = bpy.data.node_groups.new('Native Desktop Group QA', model.TREE)
        tree.use_fake_user = True
        space.node_tree, space.pin = tree, True
        panel = tree.nodes.new('NodeFrame')
        panel.label = 'Desktop Icon Panel'
        panel.location = (0, 0)
        panel.select = True
        for index, path in enumerate((file_a, file_b)):
            node = tree.nodes.new(model.FILE)
            node.filepath, node.label = str(path), path.name
            node.parent = panel
            node.location = (index * 310, index * 50)
            node.select = True
        state['positions'] = reference_rows(tree)
        delay = .4
    elif phase == 1:
        diagnostic()
        key('G', 'LEFT_CTRL')
        delay = .4
    elif phase == 2:
        diagnostic()
        with override():
            assert canvas(bpy.context) == state['area'].spaces.active.edit_tree
        assert len([node for node in root().nodes if node.bl_idname == groups.GROUP]) == 1
        group = next(node for node in root().nodes if node.bl_idname == groups.GROUP)
        assert group.type == 'CUSTOM GROUP'
        assert group.node_tree and group.node_tree.bl_idname == model.TREE
        assert not group.inputs and not group.outputs
        assert not any(node.bl_idname in {'NodeGroupInput', 'NodeGroupOutput'} for node in group.node_tree.nodes)
        assert set(reference_rows(root())) == {str(file_a), str(file_b)}
        assert any(node.bl_idname == 'NodeFrame' for node in group.node_tree.nodes)
        key('TAB')
        print('PASS Ctrl+G moves native desktop icons and their real panel into a real NodeTree', flush=True)
        delay = .3
    elif phase == 3:
        assert state['area'].spaces.active.edit_tree == root()
        group = next(node for node in root().nodes if node.bl_idname == groups.GROUP)
        root().nodes.active = group
        key('TAB')
        delay = .3
    elif phase == 4:
        group = next(node for node in root().nodes if node.bl_idname == groups.GROUP)
        with override():
            assert canvas(bpy.context) == group.node_tree
        key('TAB', 'LEFT_CTRL')
        delay = .3
    elif phase == 5:
        assert state['area'].spaces.active.edit_tree == root()
        group = next(node for node in root().nodes if node.bl_idname == groups.GROUP)
        group.select = True
        root().nodes.active = group
        key('G', 'LEFT_ALT')
        delay = .3
    elif phase == 6:
        actual = reference_rows(root())
        assert set(actual) == set(state['positions'])
        for path in actual:
            assert all(abs(actual[path][axis] - state['positions'][path][axis]) < .001 for axis in (0, 1))
        assert any(node.bl_idname == 'NodeFrame' for node in root().nodes)
        assert all(node.parent and node.parent.bl_idname == 'NodeFrame' for _owner, node in groups.file_nodes(root()))
        print('PASS Tab/Ctrl+Tab/Alt+G preserve paths, native panel parents and arranged positions', flush=True)
        delay = .3
    elif phase == 7:
        with override():
            bpy.ops.node.select_all(action='SELECT')
            assert bpy.ops.node.group_make() == {'FINISHED'}
            assert bpy.ops.node.group_edit(exit=True) == {'FINISHED'}
        first = next(node for node in root().nodes if node.bl_idname == groups.GROUP)
        second = root().nodes.new(groups.GROUP)
        second.node_tree = first.node_tree
        second.location = (700, 100)
        second.label = 'Shared desktop group'
        # Native setter must reject both direct self nesting and indirect loops.
        nested = first.node_tree.nodes.new(groups.GROUP)
        nested.node_tree = root()
        assert nested.node_tree is None
        first.node_tree.nodes.remove(nested)
        print('PASS Native recursion protection rejects an indirect desktop group loop', flush=True)
        payload = runtime.snapshot(root())
        assert payload.get('groups'), payload
        group_rows = [row for row in payload['nodes'] if row['kind'] == groups.GROUP]
        assert len(group_rows) == 2 and group_rows[0]['group'] == group_rows[1]['group']
        state['payload'] = payload
        runtime.apply_layout(root(), payload)
        group_nodes = [node for node in root().nodes if node.bl_idname == groups.GROUP]
        assert len(group_nodes) == 2 and group_nodes[0].node_tree == group_nodes[1].node_tree
        assert set(reference_rows(root())) == {str(file_a), str(file_b)}
        assert file_a.read_text(encoding='utf-8') == 'group fixture a'
        assert file_b.read_text(encoding='utf-8') == 'group fixture b'
        print('PASS Portable layout retains shared native group identity and real references', flush=True)
        delay = .3
    else:
        with override():
            bpy.ops.node.view_all()
        print('check_desktop_groups: PASS', fixture, flush=True)
        sys.stdout.flush()
        os._exit(0)
    state['phase'] += 1
    return delay


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.5)
