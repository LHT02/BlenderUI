# SPDX-License-Identifier: GPL-2.0-or-later
"""Real node/UI modals gate asynchronous canvas replacement; Undo invalidates old jobs.

Run: BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python <script>
All files/layouts belong to this QA fixture; no user CONFIG files or windows are modified.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import bpy
from bl_operators import blui_desktop as operators
from bl_ui import space_filebrowser_shell
from blui_desktop import model, runtime, session
session.disable_for_tests = True

fixture = tempfile.TemporaryDirectory(prefix='blui_canvas_stability_')
folder = Path(fixture.name)
(folder / 'async-reference.txt').write_text('QA reference only', encoding='utf-8')
state = {'phase': 0, 'started': time.monotonic()}


def window():
    return bpy.context.window_manager.windows[0]


def area():
    return window().screen.areas[0]


def tree():
    result = bpy.data.node_groups.get(state['tree_name'])
    assert result and result.bl_idname == model.TREE, 'Undo lost the canvas tree'
    return result


def context():
    editor = area()
    return bpy.context.temp_override(window=window(), area=editor,
        region=next(region for region in editor.regions if region.type == 'WINDOW'))


def point():
    region = next(region for region in area().regions if region.type == 'WINDOW')
    return (region.x + region.width // 2, region.y + region.height // 2)


def event(kind, value, xy=None):
    xy = xy or point()
    window().event_simulate(type=kind, value=value, x=xy[0], y=xy[1])


def escape():
    event('ESC', 'PRESS')
    event('ESC', 'RELEASE')


def payload(label):
    return model.validate({'version': 1, 'directory': str(folder), 'nodes': [
        {'kind': model.NOTE, 'name': label, 'note': label, 'location': [0, 0],
         'path': '', 'folder': False}]})


def queue_load(label):
    current = tree()
    value = payload(label)
    runtime._ready.append(('load', runtime.identity(current), current.scan_generation,
                           value, (0, 0), runtime.fingerprint(current)))
    return value


def assert_label(label):
    current = tree()
    assert len(current.nodes) == 1
    assert current.nodes[0].label == label and current.nodes[0].note == label


def note_field_point():
    # dimensions are native node-view units, including UI scale. Use the actual drawn bounds
    # instead of screen pixels or a hard-coded DPI. The note's single field is below its header.
    note = tree().nodes[0]
    assert note.dimensions.x > 0 and note.dimensions.y > 0, 'Note has not been drawn'
    scale = note.dimensions.x / note.width
    region = next(region for region in area().regions if region.type == 'WINDOW')
    x, y = region.view2d.view_to_region(note.location.x * scale + note.dimensions.x * .5,
        note.location.y * scale - note.dimensions.y * .67, clip=False)
    assert 0 < x < region.width and 0 < y < region.height, 'Note field is outside the fixture view'
    return (region.x + x, region.y + y)


class WM_OT_blui_canvas_qa_hold(bpy.types.Operator):
    """A fixture modal retains no editor pointers; safely exercises a cached-space switch."""
    bl_idname = 'wm.blui_canvas_qa_hold'
    bl_label = 'QA Modal Lifetime Gate'
    bl_options = {'INTERNAL', 'BLOCKING'}

    def invoke(self, context, _event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, _context, event):
        return {'CANCELLED'} if event.type == 'ESC' else {'RUNNING_MODAL'}


def step():
    if time.monotonic() - state['started'] > 45:
        raise TimeoutError('Canvas modal/Undo stability regression timed out')
    phase = state['phase']
    delay = .18
    if phase == 0:
        space_filebrowser_shell.unregister()
        if bpy.app.timers.is_registered(runtime.tick):
            bpy.app.timers.unregister(runtime.tick)
        # Deterministic polling; no OS task enumeration and never call user_resource(CONFIG).
        runtime._last_tasks = float('inf')
        runtime.layout_path = lambda _tree: str(folder / 'canvas-layout.json')
        # The stripped factory file may retain a hidden edit-mode object. Neutralize only
        # this QA scene, preserving the native memfile Undo safety policy.
        active = window().view_layer.objects.active
        if active and active.mode != 'OBJECT':
            with context():
                assert bpy.ops.object.mode_set(mode='OBJECT') == {'FINISHED'}
        with context():
            current = operators._initialize(area(), str(folder))
        runtime.cancel_pending()
        current.nodes.clear()
        note = current.nodes.new(model.NOTE)
        note.label = note.note = 'original-sentinel'
        note.location = (0, 0)
        note.select = True
        current.nodes.active = note
        state['tree_name'] = current.name
        bpy.context.preferences.edit.use_global_undo = True
        with context():
            bpy.ops.node.view_all()
            bpy.ops.ed.undo_push(message='Canvas QA original cards')
        bpy.utils.register_class(WM_OT_blui_canvas_qa_hold)
        delay = .5
    elif phase == 1:
        assert not window().blui_has_modal_interaction
        with context():
            assert bpy.ops.node.translate_attach('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
        delay = .15
    elif phase == 2:
        assert window().blui_has_modal_interaction, 'Native node macro not detected'
        state['transform_node'] = tree().nodes[0].as_pointer()
        value = queue_load('loaded-after-transform')
        runtime.tick()
        assert len(runtime._ready) == 1
        assert tree().nodes[0].as_pointer() == state['transform_node']
        assert_label('original-sentinel')
        with context():
            assert bpy.ops.wm.blui_canvas_apply(action='load', payload=json.dumps(value)) == {'CANCELLED'}
        assert_label('original-sentinel')
        print('PASS native translate_attach blocks both queued and direct destructive LOAD', flush=True)
        escape()
        delay = .25
    elif phase == 3:
        assert not window().blui_has_modal_interaction
        runtime.tick()
        assert not runtime._ready
        assert_label('loaded-after-transform')
        print('PASS Escape releases transform and queued LOAD applies through UNDO operator', flush=True)
        state['stale_identity'] = runtime.identity(tree())
        state['previous_epoch'] = runtime._epoch
        queue_load('must-not-apply-after-undo')
        state['pending_job'] = runtime.submit('paths', tree(), [str(folder / 'async-reference.txt')])
        with context():
            assert bpy.ops.ed.undo() == {'FINISHED'}
        delay = .3
    elif phase == 4:
        assert runtime._epoch > state['previous_epoch']
        assert not runtime._ready and not runtime._jobs
        assert state['pending_job'].closed
        assert runtime.resolve_tree(state['stale_identity']) is None
        assert_label('original-sentinel')
        assert runtime.cancel_pending in bpy.app.handlers.undo_pre
        assert runtime.cancel_pending in bpy.app.handlers.load_pre
        assert hasattr(runtime.cancel_pending, '_bpy_persistent')
        print('PASS native Undo restores original cards and cancels pending subprocess/results', flush=True)
        with context():
            bpy.ops.node.view_all()
        delay = .35
    elif phase == 5:
        state['field'] = note_field_point()
        event('MOUSEMOVE', 'NOTHING', state['field'])
        event('LEFTMOUSE', 'PRESS', state['field'])
        event('LEFTMOUSE', 'RELEASE', state['field'])
        delay = .2
    elif phase == 6:
        assert window().blui_has_modal_interaction, 'Native note text editor not detected at %r' % (state['field'],)
        state['text_node'] = tree().nodes[0].as_pointer()
        queue_load('loaded-after-text-edit')
        runtime.tick()
        assert len(runtime._ready) == 1
        assert tree().nodes[0].as_pointer() == state['text_node']
        assert_label('original-sentinel')
        print('PASS native note text-edit UI retains its node while async LOAD waits', flush=True)
        escape()
        delay = .25
    elif phase == 7:
        assert not window().blui_has_modal_interaction
        runtime.tick()
        assert not runtime._ready
        assert_label('loaded-after-text-edit')
        print('PASS Escape closes native text editing and safely applies the queued layout', flush=True)
        with context():
            assert bpy.ops.wm.blui_canvas_qa_hold('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
        delay = .15
    elif phase == 8:
        assert window().blui_has_modal_interaction
        state['cached_tree'] = runtime.identity(tree())
        queue_load('loaded-after-cached-space')
        area().type = 'TEXT_EDITOR'
        assert any(space.type == 'NODE_EDITOR' and space.node_tree == tree() for space in area().spaces)
        assert window().blui_has_modal_interaction and runtime.interaction_busy(tree())
        runtime.tick()
        assert len(runtime._ready) == 1
        assert_label('loaded-after-text-edit')
        area().type = 'NODE_EDITOR'
        assert runtime.identity(area().spaces.active.node_tree) == state['cached_tree']
        runtime.tick()
        assert len(runtime._ready) == 1, 'Restoring the editor bypassed the still-active window modal'
        print('PASS modal gate remains active when canvas is cached behind a different editor', flush=True)
        escape()
        delay = .25
    else:
        assert not window().blui_has_modal_interaction
        runtime.tick()
        assert not runtime._ready
        assert_label('loaded-after-cached-space')
        runtime.cancel_pending()
        bpy.utils.unregister_class(WM_OT_blui_canvas_qa_hold)
        fixture.cleanup()
        print('check_canvas_stability: PASS (native node/UI modal gates, Undo cancellation, cached editor)', flush=True)
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
