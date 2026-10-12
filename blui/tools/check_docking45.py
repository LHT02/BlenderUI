# SPDX-License-Identifier: GPL-2.0-or-later
"""Real windows: four dock edges, identity-preserving move, replacement guard and join."""
import os
from pathlib import Path
import sys
import tempfile
import time
import bpy
from bl_operators import blui_documents as documents
from bl_ui import space_filebrowser_shell

root = Path(tempfile.mkdtemp(prefix='blui_docking45_'))
state = {'step': 0, 'started': time.monotonic(), 'edge': 0}
edges = ('LEFT', 'RIGHT', 'TOP', 'BOTTOM')


def context(window, area=None):
    area = area or window.screen.areas[0]
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    return bpy.context.temp_override(window=window, area=area, region=region)


def source_window(name):
    before = {window.as_pointer() for window in bpy.context.window_manager.windows}
    with context(state['root']):
        bpy.ops.wm.window_new(workspace=state['text_workspace'])
    window = next(window for window in bpy.context.window_manager.windows if window.as_pointer() not in before)
    area = window.screen.areas[0]
    area.type = 'TEXT_EDITOR'
    text = bpy.data.texts.new(name)
    text.write('unsaved buffer: ' + name)
    area.spaces.active.text = text
    state.update(source=window, source_id=window.as_pointer(), source_area=area,
                 source_space=area.spaces.active.as_pointer(), text=text)


def dock(target, location, factor=.25):
    source, area = state['source'], state['source_area']
    with context(source, area):
        return bpy.ops.screen.area_dock(source_window=str(source.as_pointer()), source_area=str(area.as_pointer()),
            source_space=str(state['source_space']), target_window=str(state['root'].as_pointer()),
            target_area=str(target.as_pointer()), dock_target=location, factor=factor)


def decision(choice, succeeds=True):
    token, request = next((token, request) for token, request in documents._requests.items() if request.action == 'DOCK')
    for value in ('PRESS', 'RELEASE'):
        request.window.event_simulate(type='ESC', value=value)
    result = None
    try:
        with context(request.window, request.area):
            result = bpy.ops.wm.blui_document_decision(token=token, choice=choice)
    except RuntimeError:
        assert not succeeds
    if succeeds:
        assert result == {'FINISHED'}
    else:
        assert result != {'FINISHED'}


def event(kind, value, point, **modifiers):
    state['root'].event_simulate(type=kind, value=value, x=point[0], y=point[1], **modifiers)


def step():
    if time.monotonic() - state['started'] > 65:
        raise TimeoutError('Docking regression timed out')
    n = state['step']
    if n == 0:
        space_filebrowser_shell.unregister()
        state['root'] = bpy.context.window_manager.windows[0]
        state['text_workspace'] = next(workspace.name for workspace in bpy.data.workspaces
            if any(area.type == 'TEXT_EDITOR' for screen in workspace.screens for area in screen.areas))
        source_window('edge-' + edges[0])
        delay = .4
    elif n == 1:
        target = next(area for area in state['root'].screen.areas if area.type == 'FILE_BROWSER')
        state['target_width'], state['target_height'] = target.width, target.height
        assert dock(target, edges[state['edge']]) == {'FINISHED'}
        delay = .4
    elif n == 2:
        assert state['source_id'] not in {window.as_pointer() for window in bpy.context.window_manager.windows}
        areas = list(state['root'].screen.areas)
        assert len(areas) == 2
        moved = next(area for area in areas if area.type == 'TEXT_EDITOR')
        assert moved.spaces.active.text == state['text']
        assert moved.spaces.active.as_pointer() == state['source_space'], 'Editor was cloned rather than moved'
        assert moved.spaces.active.text.as_string().startswith('unsaved buffer: edge-')
        expected = state['target_width'] if edges[state['edge']] in {'LEFT', 'RIGHT'} else state['target_height']
        actual = moved.width if edges[state['edge']] in {'LEFT', 'RIGHT'} else moved.height
        assert abs(actual - expected * .25) < 8, (edges[state['edge']], actual, expected)
        print('PASS Dock', edges[state['edge']], 'moves the same editor and buffer; source window closes', flush=True)
        with context(state['root'], moved):
            bpy.ops.screen.area_close(confirmed=True)
        delay = .3
    elif n == 3:
        state['edge'] += 1
        if state['edge'] < len(edges):
            source_window('edge-' + edges[state['edge']])
            state['step'] = 1
            return .4
        target = state['root'].screen.areas[0]
        target.type = 'TEXT_EDITOR'
        target_text = bpy.data.texts.new('destination-unsaved')
        target_text.filepath = str(root / 'destination.txt')
        target_text.write('destination saved before replacement')
        target.spaces.active.text = target_text
        state.update(target=target, target_text=target_text, target_space=target.spaces.active)
        target.type = 'FILE_BROWSER'  # The dirty text remains in this area's inactive cache.
        source_window('replacement-source')
        delay = .4
    elif n == 4:
        assert dock(state['target'], 'CENTER') == {'FINISHED'}
        assert state['target_space'].text == state['target_text']
        decision('CANCEL')
        assert state['source_id'] in {window.as_pointer() for window in bpy.context.window_manager.windows}
        assert state['target'].type == 'FILE_BROWSER' and state['target_space'].text == state['target_text']
        print('PASS Cancelling center replacement keeps both windows and unsaved documents', flush=True)
        assert dock(state['target'], 'CENTER') == {'FINISHED'}
        decision('SAVE')
        delay = .4
    elif n == 5:
        assert state['source_id'] not in {window.as_pointer() for window in bpy.context.window_manager.windows}
        assert state['target'].spaces.active.text == state['text']
        assert (root / 'destination.txt').read_text(encoding='utf-8') == 'destination saved before replacement'
        print('PASS Saving the target precedes center replacement and preserves the incoming unsaved buffer', flush=True)
        source_window('stale-source')
        delay = .4
    elif n == 6:
        assert dock(state['target'], 'CENTER') == {'FINISHED'}
        state['source_area'].type = 'CONSOLE'
        current = state['target'].spaces.active.text
        decision('DISCARD', succeeds=False)
        assert state['target'].spaces.active.text == current
        with context(state['source']):
            bpy.ops.wm.window_close(force_close=True)
        print('PASS Source-editor changes during confirmation cancel docking without replacing the target', flush=True)
        delay = .3
    elif n == 7:
        area = state['root'].screen.areas[0]
        point = (area.x + 2, area.y + 2)
        middle = (area.x + area.width // 2, area.y + 60)
        state.update(point=point, middle=middle)
        event('MOUSEMOVE', 'NOTHING', point)
        event('LEFTMOUSE', 'PRESS', point)
        delay = .2
    elif n == 8:
        event('MOUSEMOVE', 'NOTHING', state['middle'], ctrl=True)
        delay = .3
    elif n == 9:
        assert len(state['root'].screen.areas) == 1, 'Split mutated layout before release'
        with context(state['root']):
            bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[3] / 'build/dock-split-preview.png'))
        event('LEFTMOUSE', 'RELEASE', state['middle'], ctrl=True)
        delay = .4
    elif n == 10:
        areas = list(state['root'].screen.areas)
        assert len(areas) == 2, 'Unified native corner did not split'
        assert all(area.spaces.active.text == areas[0].spaces.active.text for area in areas)
        print('PASS Unified native corner previews without mutation; Ctrl-snapped split commits on release', flush=True)
        source, target = sorted(areas, key=lambda area: area.x)
        state['join_source'] = source
        with context(state['root'], source):
            bpy.ops.screen.area_join(source_xy=(source.x + source.width // 2, source.y + source.height // 2),
                                    target_xy=(target.x + target.width // 2, target.y + target.height // 2))
        decision('CANCEL')
        assert len(state['root'].screen.areas) == 2
        with context(state['root'], source):
            bpy.ops.screen.area_join(source_xy=(source.x + source.width // 2, source.y + source.height // 2),
                                    target_xy=(target.x + target.width // 2, target.y + target.height // 2))
        decision('DISCARD')
        delay = .3
    elif n == 11:
        assert len(state['root'].screen.areas) == 1
        assert state['root'].screen.areas[0].spaces.active.text.as_string() == 'unsaved buffer: replacement-source'
        print('PASS Native adjacent join supports cancellation and preserves the kept buffer', flush=True)
        print('check_docking45: PASS', root, flush=True)
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


bpy.app.timers.register(guarded, first_interval=.5)
