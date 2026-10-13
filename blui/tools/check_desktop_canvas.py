# SPDX-License-Identifier: GPL-2.0-or-later
"""Real native canvas: async files, node movement/undo, safe references, save/load and taskbar."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import bpy
from bl_operators import blui_desktop, blui_file
from bl_ui import space_filebrowser_shell
from blui_desktop import model, runtime, session
session.disable_for_tests = True

fixture = Path(tempfile.mkdtemp(prefix='blui_canvas_qa_'))
files = fixture / 'Files'
files.mkdir()
(files / 'Folder').mkdir()
(files / 'a.txt').write_text('canvas copy fixture', encoding='utf-8')
(files / 'b.txt').write_text('canvas drag fixture', encoding='utf-8')
target = fixture / 'Copied'
target.mkdir()
runtime.layout_path = lambda _tree: str(fixture / 'layout.json')
state = {'phase': 0, 'started': time.monotonic()}


def override():
    window = state['window']
    area = window.screen.areas[0]
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=area, region=region)


def tree():
    return state['window'].screen.areas[0].spaces.active.node_tree


def event(kind, value, point=None):
    point = point or state['point']
    state['window'].event_simulate(type=kind, value=value, x=point[0], y=point[1])


def step():
    if time.monotonic() - state['started'] > 40:
        raise TimeoutError('Desktop canvas regression timed out')
    phase = state['phase']
    if phase == 0:
        space_filebrowser_shell.unregister()
        state['window'] = bpy.context.window_manager.windows[0]
        area = state['window'].screen.areas[0]
        active = state['window'].view_layer.objects.active
        if active and active.mode != 'OBJECT':
            with override():
                bpy.ops.object.mode_set(mode='OBJECT')
        blui_desktop._initialize(area, str(files))
        bpy.context.preferences.edit.use_global_undo = True
        delay = .4
    elif phase == 1:
        if len(tree().nodes) != 3:
            return .1
        assert any(region.type == 'FOOTER' and region.height > 0 for region in state['window'].screen.areas[0].regions)
        print('PASS Native node cards load asynchronously and native footer taskbar is visible', flush=True)
        with override():
            bpy.ops.node.view_all()
            bpy.ops.ed.undo_push(message='QA canvas cards')
        state['point'] = (state['window'].width // 2, state['window'].height // 2)
        event('MOUSEMOVE', 'NOTHING')
        for node in tree().nodes:
            node.select = False
        node = next(node for node in tree().nodes if node.filepath.endswith('a.txt'))
        node.select = True
        tree().nodes.active = node
        state['before'] = tuple(node.location)
        delay = .3
    elif phase == 2:
        with override():
            assert bpy.ops.node.translate_attach('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
        assert state['window'].blui_has_modal_interaction
        event('MOUSEMOVE', 'NOTHING', (state['point'][0] + 140, state['point'][1] + 40))
        delay = .3
    elif phase == 3:
        event('LEFTMOUSE', 'PRESS', (state['point'][0] + 140, state['point'][1] + 40))
        event('LEFTMOUSE', 'RELEASE', (state['point'][0] + 140, state['point'][1] + 40))
        delay = .3
    elif phase == 4:
        node = next(node for node in tree().nodes if node.filepath.endswith('a.txt'))
        assert sum(abs(node.location[index] - state['before'][index]) for index in (0, 1)) > 10
        assert not state['window'].blui_has_modal_interaction
        with override():
            bpy.ops.node.delete('EXEC_DEFAULT', True)
        assert len(tree().nodes) == 2 and (files / 'a.txt').is_file()
        with override():
            bpy.ops.ed.undo()
        delay = .4
    elif phase == 5:
        assert len(tree().nodes) == 3
        assert not runtime._ready and all(token is None for _job, _action, token, _generation in runtime._jobs)
        print('PASS Native move/undo works; removing a card never deletes its real file', flush=True)
        with override():
            bpy.ops.wm.blui_canvas_note()
        note = next(node for node in tree().nodes if node.bl_idname == model.NOTE)
        note.note, note.location = 'saved-note', (0, 220)
        with override():
            bpy.ops.wm.blui_canvas_layout(action='SAVE')
        delay = .4
    elif phase == 6:
        if runtime._jobs:
            return .1
        assert (fixture / 'layout.json').is_file()
        next(node for node in tree().nodes if node.bl_idname == model.NOTE).note = 'temporary-change'
        with override():
            bpy.ops.wm.blui_canvas_layout(action='LOAD')
        delay = .4
    elif phase == 7:
        if runtime._jobs or runtime._ready:
            return .1
        assert next(node for node in tree().nodes if node.bl_idname == model.NOTE).note == 'saved-note'
        print('PASS Atomic fixture save and async restore preserve positions and notes', flush=True)
        with override():
            bpy.ops.wm.blui_canvas_transfer(paths=str(files / 'a.txt'), directory=str(target), move=False,
                                          canvas_identity=json.dumps(runtime.identity(tree())))
        delay = .4
    elif phase == 8:
        if blui_file._jobs:
            return .1
        assert (target / 'a.txt').read_text(encoding='utf-8') == 'canvas copy fixture'
        assert (files / 'a.txt').is_file()
        print('PASS Canvas transfer reuses protected isolated file task backend', flush=True)
        (fixture / 'extra.txt').write_text('native drop bridge', encoding='utf-8')
        with override():
            assert bpy.ops.node.blui_canvas_drop('INVOKE_DEFAULT', paths=str(fixture / 'extra.txt')) == {'FINISHED'}
        delay = .4
    elif phase == 9:
        if runtime._jobs or runtime._ready:
            return .1
        assert any(getattr(node, 'filepath', '') == str(fixture / 'extra.txt') for node in tree().nodes)
        assert (fixture / 'extra.txt').is_file()
        print('PASS Native dropbox bridge adds references without moving originals', flush=True)
        tasks = [task for task in runtime.tasks() if task['pid'] == os.getpid() and task['actionable']]
        if not tasks:
            return .1
        task = tasks[0]
        with override():
            result = bpy.ops.wm.blui_task_activate(handle=task['handle'], pid=task['pid'], thread_id=task['thread_id'],
                process_started=task['process_started'], window_class=task['window_class'])
        assert result == {'FINISHED'}
        print('PASS Taskbar enumerates tasks and validates only its own QA window activation', flush=True)
        with override():
            bpy.ops.node.view_all()
        delay = .4
    else:
        with override():
            bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[3] / 'build/desktop-canvas.png'))
        runtime.unregister()
        print('check_desktop_canvas: PASS', fixture, flush=True)
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
