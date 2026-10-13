# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise file-browser layout destruction and repeated native corner detach, in QA windows only.

Run with BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python <script>.
This is a regression for the real file_context -> CTX_data_main -> screen_dock_apply crash.
"""
import base64
import os
import sys
import tempfile
import time
from pathlib import Path

import bpy

fixture = tempfile.TemporaryDirectory(prefix='blui_dock_stability_')
folder = Path(fixture.name)
pixel = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')
for index in range(250):
    (folder / ('preview-%03d.png' % index)).write_bytes(pixel)

state = {'phase': 0, 'cycle': 0, 'started': time.monotonic()}


def override(window, area):
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    return bpy.context.temp_override(window=window, area=area, region=region)


def file_area(area):
    area.type = 'FILE_BROWSER'
    area.spaces.active.params.directory = os.fsencode(str(folder) + os.sep)
    area.spaces.active.params.display_type = 'THUMBNAIL'


def dock(window, source, target, side):
    arguments = dict(source_window=str(window.as_pointer()), source_area=str(source.as_pointer()),
                     source_space=str(source.spaces.active.as_pointer()),
                     target_window=str(window.as_pointer()), target_area=str(target.as_pointer()),
                     dock_target=side, factor=.25, confirmed=True)
    with override(window, target):
        assert bpy.ops.screen.area_dock(**arguments) == {'FINISHED'}


def event(kind, value, point):
    state['window'].event_simulate(type=kind, value=value, x=point[0], y=point[1])


def step():
    if time.monotonic() - state['started'] > 90:
        raise TimeoutError('Window/file-browser stability regression timed out')
    phase, cycle = state['phase'], state['cycle']
    if phase == 0:
        window = bpy.context.window_manager.windows[0]
        assert isinstance(window.blui_has_modal_interaction, bool)
        assert bpy.types.Window.bl_rna.properties['blui_has_modal_interaction'].is_readonly
        area = window.screen.areas[0]
        file_area(area)
        if cycle < 24:
            with override(window, area):
                assert bpy.ops.screen.area_split(direction='VERTICAL', factor=.5) == {'FINISHED'}
            source = next(a for a in window.screen.areas if a != area)
            file_area(source)
            identity = source.spaces.active.as_pointer()
            # This frees a FILE_BROWSER source inside screen_dock_apply. The previous build
            # queried CTX_data_main with C->wm.area still pointing at that freed area.
            side = ('LEFT', 'RIGHT', 'TOP', 'BOTTOM')[cycle % 4]
            dock(window, source, area, side)
            moved = next(a for a in window.screen.areas
                         if a.spaces.active.as_pointer() == identity)
            target = next(a for a in window.screen.areas if a != moved)
            dock(window, moved, target, 'CENTER')
            assert len(window.screen.areas) == 1
            assert window.screen.areas[0].spaces.active.as_pointer() == identity
            assert bpy.context.blend_data.filepath == bpy.data.filepath
            state['cycle'] += 1
            print('PASS file-browser dock/close cycle', cycle + 1, side, flush=True)
            return .08
        if cycle < 28:
            with override(window, area):
                assert bpy.ops.screen.area_split(direction='VERTICAL', factor=.5) == {'FINISHED'}
            left, right = sorted(window.screen.areas, key=lambda a: a.x)
            with override(window, left):
                assert bpy.ops.screen.area_split(direction='HORIZONTAL', factor=.5) == {'FINISHED'}
            targets = sorted((a for a in window.screen.areas if a != right), key=lambda a: a.y)
            target = targets[cycle % 2]
            # Joining a tall source into a short neighbor trims/free its remainder. The
            # original source pointer is not guaranteed to be the surviving aligned area.
            dock(window, right, target, 'JOIN')
            while len(window.screen.areas) > 1:
                remaining = list(window.screen.areas)
                dock(window, remaining[-1], remaining[0], 'CENTER')
            print('PASS partial-edge join trims source remainder safely', cycle - 23, flush=True)
            state['cycle'] += 1
            return .1
        corner = (cycle - 28) % 4
        right, top = bool(corner & 1), bool(corner & 2)
        point = (area.x + area.width - 3 if right else area.x + 2,
                 area.y + area.height - 3 if top else area.y + 2)
        outside = (window.width + 40 if right else -40, window.height + 40 if top else -40)
        state.update(window=window, identity=area.spaces.active.as_pointer(), point=point,
                     outside=outside, before={w.as_pointer() for w in bpy.context.window_manager.windows})
        state.pop('wait_at', None)
        delay = .18
    elif phase == 1:
        event('MOUSEMOVE', 'NOTHING', state['point'])
        event('LEFTMOUSE', 'PRESS', state['point'])
        delay = .08
    elif phase == 2:
        assert state['window'].blui_has_modal_interaction, 'Corner modal must block asynchronous editor replacement'
        event('MOUSEMOVE', 'NOTHING', state['outside'])
        delay = .12
    elif phase == 3:
        event('LEFTMOUSE', 'RELEASE', state['outside'])
        delay = .22
    else:
        windows = list(bpy.context.window_manager.windows)
        created = [w for w in windows if w.as_pointer() not in state['before']]
        if len(created) == 1 and len(windows) > 1:
            state.setdefault('wait_at', time.monotonic())
            if time.monotonic() - state['wait_at'] < 3:
                return .05
        assert len(windows) == 1 and len(created) == 1, 'Detach did not finish moving source window'
        assert not created[0].blui_has_modal_interaction, 'Finished move retained a stale modal handler'
        assert created[0].screen.areas[0].spaces.active.as_pointer() == state['identity']
        assert created[0].screen.areas[0].type == 'FILE_BROWSER'
        print('PASS thumbnail file-browser native corner detach', cycle - 27, flush=True)
        state['cycle'] += 1
        if state['cycle'] == 36:
            state['phase'] = 6
            return .12
        state['phase'] = 0
        return .12
    state['phase'] += 1
    return delay


def guarded():
    try:
        if state['phase'] == 6:
            window = bpy.context.window_manager.windows[0]
            area = window.screen.areas[0]
            before = {w.as_pointer() for w in bpy.context.window_manager.windows}
            with override(window, area):
                assert bpy.ops.wm.window_new() == {'FINISHED'}
            replacement = next(w for w in bpy.context.window_manager.windows
                               if w.as_pointer() not in before)
            with override(window, area):
                assert bpy.ops.wm.blui_close_moved_window(
                    source=str(window.as_pointer()), replacement=str(replacement.as_pointer()),
                    source_space=str(area.spaces.active.as_pointer())) == {'FINISHED'}
            # Model an editor/workspace change already queued when deferred close was registered.
            area.type = 'TEXT_EDITOR'
            text = bpy.data.texts.new('must-not-close-after-source-changed')
            text.write('deferred close cancels instead of discarding this new document')
            area.spaces.active.text = text
            state.update(window_id=window.as_pointer(), retained_text=text)
            state['phase'] = 7
            return .2
        if state['phase'] == 7:
            windows = list(bpy.context.window_manager.windows)
            assert len(windows) == 2
            window = next(w for w in windows if w.as_pointer() == state['window_id'])
            assert window.screen.areas[0].spaces.active.text == state['retained_text']
            print('PASS queued source-editor change cancels deferred close without discarding new data', flush=True)
            target_window = next(w for w in windows if w != window)
            target_area = target_window.screen.areas[0]
            stale_target = target_area.spaces.active.as_pointer()
            target_area.type = 'TEXT_EDITOR'
            target_text = bpy.data.texts.new('target-editor-changed-while-confirming')
            target_text.write('a newer target editor must not be replaced by stale confirmation')
            target_area.spaces.active.text = target_text
            source = window.screen.areas[0]
            result = None
            try:
                with override(window, source):
                    result = bpy.ops.screen.area_dock(
                        source_window=str(window.as_pointer()), source_area=str(source.as_pointer()),
                        source_space=str(source.spaces.active.as_pointer()),
                        target_window=str(target_window.as_pointer()), target_area=str(target_area.as_pointer()),
                        target_space=str(stale_target), dock_target='CENTER', confirmed=True)
            except RuntimeError:
                pass  # Native rejection reports an operator error to Python.
            assert result != {'FINISHED'} and target_area.spaces.active.text == target_text
            print('PASS stale target-editor identity rejects replacement without losing either document', flush=True)
            state.update(window=window, before={w.as_pointer() for w in windows},
                         point=(source.x + source.width - 3, source.y + source.height - 3),
                         outside=(window.width + 40, window.height + 40))
            state['phase'] = 8
            return .15
        if state['phase'] == 8:
            event('MOUSEMOVE', 'NOTHING', state['point'])
            event('LEFTMOUSE', 'PRESS', state['point'])
            state['phase'] = 9
            return .1
        if state['phase'] == 9:
            assert state['window'].blui_has_modal_interaction
            event('MOUSEMOVE', 'NOTHING', state['outside'])
            state['phase'] = 10
            return .15
        if state['phase'] == 10:
            state['window'].screen.areas[0].type = 'CONSOLE'
            event('LEFTMOUSE', 'RELEASE', state['outside'])
            state['phase'] = 11
            return .2
        if state['phase'] == 11:
            assert {w.as_pointer() for w in bpy.context.window_manager.windows} == state['before']
            assert state['window'].screen.areas[0].type == 'CONSOLE'
            assert not state['window'].blui_has_modal_interaction
            print('PASS source-editor changes during native drag cancel the stale modal safely', flush=True)
            print('check_docking_stability: PASS (48 mutations + 4 partial joins + 8 detaches + stale close/target/drag)', flush=True)
            fixture.cleanup()
            sys.stdout.flush()
            os._exit(0)
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.5)
