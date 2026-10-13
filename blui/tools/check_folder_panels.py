# SPDX-License-Identifier: GPL-2.0-or-later
"""Own native canvas folder panel, asynchronous reconciliation and portable persistence."""
import os
from pathlib import Path
import sys
import tempfile
import time
import bpy
from bl_operators import blui_desktop
from blui_desktop import folder_panels, model, runtime, session

session.disable_for_tests = True
fixture = Path(tempfile.mkdtemp(prefix='blui_folder_panel_qa_'))
folder = fixture / 'Mapped'
folder.mkdir()
(folder / 'a.txt').write_text('private A', encoding='utf-8')
(folder / 'b.txt').write_text('private B', encoding='utf-8')
state = {'phase': 0, 'started': time.monotonic()}


def owner():
    window = state['window']
    area = window.screen.areas[0]
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=area, region=region)


def tree():
    return state['window'].screen.areas[0].spaces.active.node_tree


def frame():
    return folder_panels.frame_by_id(tree(), state['frame'])


def children():
    return [node for node in tree().nodes if node.parent == frame()]


def step():
    if time.monotonic() - state['started'] > 40:
        raise TimeoutError('Native folder panel QA timed out')
    phase = state['phase']
    if phase == 0:
        state['window'] = bpy.context.window_manager.windows[0]
        area = state['window'].screen.areas[0]
        with owner():
            active = bpy.context.view_layer.objects.active
            if active and active.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        blui_desktop._initialize(area, str(fixture))
        state['phase'] = 1
        return .3
    if phase == 1:
        if runtime._jobs:
            return .1
        with owner():
            assert bpy.ops.wm.blui_folder_panel_add(directory=str(folder)) == {'FINISHED'}
        state['frame'] = tree().nodes.active['blui_id']
        state['phase'] = 2
        return .3
    if phase == 2:
        if folder_panels._pending or folder_panels._ready:
            return .1
        assert len(children()) == 2
        keep = next(node for node in children() if node.label == 'a.txt')
        keep.location = (333, -199)
        state['keep'] = keep['blui_id']
        manual = tree().nodes.new(model.FILE)
        manual.filepath, manual.label, manual.parent = str(fixture / 'manual.txt'), 'manual', frame()
        manual.location = (-150, 120)
        state['manual'] = manual['blui_id']
        (folder / 'b.txt').unlink()
        (folder / 'c.txt').write_text('private C', encoding='utf-8')
        with owner():
            assert bpy.ops.wm.blui_folder_panel_refresh(frame=state['frame']) == {'FINISHED'}
        state['phase'] = 3
        return .3
    if phase == 3:
        if folder_panels._pending or folder_panels._ready:
            return .1
        cards = children()
        assert sorted(node.label for node in cards) == ['a.txt', 'c.txt', 'manual']
        keep = next(node for node in cards if node['blui_id'] == state['keep'])
        assert tuple(keep.location) == (333, -199)
        assert any(node['blui_id'] == state['manual'] for node in cards)
        assert (folder / 'a.txt').is_file() and (folder / 'c.txt').is_file()
        snapshot = runtime.snapshot(tree())
        saved = model.save(fixture / 'layout.json', snapshot)
        restored = model.load(saved)
        assert snapshot == restored
        runtime.apply_layout(tree(), restored)
        assert frame()['blui_folder'] == str(folder)
        assert frame().use_custom_color
        assert len(children()) == 3
        assert all(node.get('blui_portal_owner') == state['frame'] for node in children() if node.label != 'manual')
        print('PASS Native Frame folder scan, stable positions, manual references, removal-only references and color/layout restore', flush=True)
        original = frame()
        other = fixture / 'Other'
        other.mkdir()
        (other / 'd.txt').write_text('private D', encoding='utf-8')
        duplicate = tree().nodes.new(model.FRAME)
        duplicate['blui_id'], duplicate['blui_folder'] = original['blui_id'], str(other)
        copied = tree().nodes.new(model.FILE)
        copied.filepath, copied.label, copied.parent = str(folder / 'a.txt'), 'a.txt', duplicate
        copied['blui_portal_owner'] = original['blui_id']
        tree().nodes.active = duplicate
        with owner():
            assert bpy.ops.wm.blui_folder_panel_refresh(frame=duplicate['blui_id']) == {'FINISHED'}
        state['duplicate'] = duplicate['blui_id']
        assert state['duplicate'] != state['frame']
        assert copied['blui_portal_owner'] == state['duplicate']
        state['phase'] = 4
        return .3
    if phase == 4:
        if folder_panels._pending or folder_panels._ready:
            return .1
        duplicate = folder_panels.frame_by_id(tree(), state['duplicate'])
        assert [node.label for node in tree().nodes if node.parent == duplicate] == ['d.txt']
        assert sorted(node.label for node in children()) == ['a.txt', 'c.txt', 'manual']
        print('PASS First refresh of duplicated Frame targets only active duplicate and remaps managed ownership', flush=True)
        # Stale queued replies cannot find deleted frames and must never re-create them.
        folder_panels.request(tree(), frame())
        tree().nodes.remove(frame())
        state['phase'] = 5
        return .3
    if phase == 5:
        if folder_panels._pending or folder_panels._ready:
            return .1
        assert frame() is None
        print('check_folder_panels: PASS (stale panel reply discarded)', flush=True)
        from blui_desktop import groups
        nested = bpy.data.node_groups.new('QA graph budget', model.TREE)
        for index in range(950):
            nested.nodes.new(model.NOTE)
        group = tree().nodes.new(model.GROUP)
        group.node_tree = nested
        duplicate = folder_panels.frame_by_id(tree(), state['duplicate'])
        folder_panels.apply(tree(), duplicate, {'rows': [
            {'path': str(fixture / f'budget-{index}.txt'), 'name': f'budget-{index}.txt', 'folder': False}
            for index in range(200)], 'truncated': False})
        assert sum(1 for _owner, node in groups.walk(tree())) <= model.LIMIT
        assert model.validate(runtime.snapshot(tree()))
        print('PASS Folder panel respects full native group graph budget and remains serializable', flush=True)
        os._exit(0)


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.8)
