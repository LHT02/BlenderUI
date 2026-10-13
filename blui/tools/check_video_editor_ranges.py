# SPDX-License-Identifier: GPL-2.0-or-later
"""Per-SpaceSeq ranges, native playback, copying and saved/legacy file loading.

Run as the sole GUI QA process with --factory-startup --enable-event-simulate
--python-exit-code 1 --python this_file.py. Saves only a temporary QA project.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import bpy
from bpy.app.handlers import persistent

SOURCE = Path(__file__).resolve().parents[2]
legacy = Path(os.environ.get('BLUI_QA_LEGACY_STARTUP',
    str(SOURCE.parent / 'dist/BLUI-1.0.0-windows-x64-20261012-docking/1.0/datafiles/startup.blend')))
fixture = Path(tempfile.mkdtemp(prefix='blui_video_ranges_'))
state = {'phase': 0, 'started': time.monotonic(), 'frames': []}


def window():
    return bpy.context.window_manager.windows[0]


def areas():
    return sorted((area for area in window().screen.areas if area.type == 'SEQUENCE_EDITOR'),
                  key=lambda area: area.x)


def override(area):
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return bpy.context.temp_override(window=window(), area=area, region=region)


def bounds(area):
    space = area.spaces.active
    return space.timeline_start, space.timeline_end


def scene_bounds():
    scene = bpy.context.scene
    return scene.frame_start, scene.frame_end, scene.use_preview_range, scene.frame_preview_start, scene.frame_preview_end


def focus(area):
    region = next(region for region in area.regions if region.type == 'WINDOW')
    window().event_simulate(type='MOUSEMOVE', value='NOTHING',
                            x=region.x + region.width // 2, y=region.y + region.height // 2)


@persistent
def record_frame(scene, _depsgraph=None):
    if state.get('record'):
        state['frames'].append(scene.frame_current)


def step():
    if time.monotonic() - state['started'] > 50:
        raise TimeoutError('Video range regression timed out')
    phase = state['phase']
    if phase == 0:
        from blui_desktop import runtime
        from bl_ui import space_filebrowser_shell
        runtime.unregister()
        space_filebrowser_shell.unregister()
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 3, 400
        scene.use_preview_range = True
        scene.frame_preview_start, scene.frame_preview_end = 30, 90
        state['global'] = scene_bounds()
        state['initial_frame'] = scene.frame_current
        area = max(window().screen.areas, key=lambda area: area.width * area.height)
        area.type = 'SEQUENCE_EDITOR'
        with override(area):
            assert bpy.ops.screen.area_split(direction='VERTICAL', factor=.5) == {'FINISHED'}
        return advance(.4)
    if phase == 1:
        first, second = areas()
        assert bounds(first) == bounds(second)
        first.spaces.active.timeline_start, first.spaces.active.timeline_end = 11, 16
        second.spaces.active.timeline_start, second.spaces.active.timeline_end = 101, 106
        assert bounds(first) == (11, 16) and bounds(second) == (101, 106)
        assert scene_bounds() == state['global']
        assert bpy.context.scene.frame_current == state['initial_frame']
        first.spaces.active.timeline_start = 20
        assert bounds(first) == (20, 20)
        first.spaces.active.timeline_end = 5
        assert bounds(first) == (5, 5)
        first.spaces.active.timeline_start, first.spaces.active.timeline_end = 11, 16
        # Native strip range action must not silently write Scene bounds anymore.
        scene = bpy.context.scene
        editor = scene.sequence_editor_create()
        strip = editor.sequences.new_effect('Video range QA color', type='COLOR', channel=1,
                                            frame_start=8, frame_end=30)
        strip.select = True
        state['strip'] = (strip.name, strip.frame_start, strip.frame_final_duration)
        with override(first):
            assert bpy.ops.sequencer.set_range_to_strips() == {'FINISHED'}
        assert bounds(first) == (8, 29) and bounds(second) == (101, 106)
        assert scene_bounds() == state['global']
        with override(first):
            assert bpy.ops.anim.previewrange_clear() == {'FINISHED'}
        assert bounds(first) == (3, 400) and bounds(second) == (101, 106)
        assert scene_bounds() == state['global']
        first.spaces.active.timeline_start, first.spaces.active.timeline_end = 11, 16
        with override(first):
            assert bpy.ops.screen.frame_jump(end=False) == {'FINISHED'}
        assert scene.frame_current == 11
        with override(second):
            assert bpy.ops.screen.frame_jump(end=True) == {'FINISHED'}
        assert scene.frame_current == 106
        print('PASS Independent validated local ranges, strips/reset/jump do not alter global bounds', flush=True)
        scene.frame_set(11)
        state['record'] = True
        bpy.app.handlers.frame_change_post.append(record_frame)
        with override(first):
            assert bpy.ops.screen.animation_play(sync=False) == {'FINISHED'}
        focus(second)
        return advance(.6)
    if phase == 2:
        assert state['frames'] and set(state['frames']).issubset(set(range(11, 17))), state['frames']
        first, second = areas()
        first.spaces.active.timeline_start, first.spaces.active.timeline_end = 601, 606
        # Dispose of the initiating editor's active regions: the timer only owns values.
        first.type = 'IMAGE_EDITOR'
        assert not hasattr(first.spaces.active, 'timeline_start')
        focus(second)
        state['frames'].clear()
        return advance(.5)
    if phase == 3:
        assert state['frames'] and set(state['frames']).issubset(set(range(11, 17))), state['frames']
        second = areas()[0]
        with override(second):
            bpy.ops.screen.animation_cancel(restore_frame=False)
        state['record'] = False
        assert scene_bounds() == state['global']
        inactive = next(area for area in window().screen.areas if area.type == 'IMAGE_EDITOR')
        inactive.type = 'SEQUENCE_EDITOR'
        assert bounds(inactive) == (601, 606)
        inactive.type = 'TEXT_EDITOR'
        assert not hasattr(inactive.spaces.active, 'timeline_start')
        inactive.type = 'SEQUENCE_EDITOR'
        assert bounds(inactive) == (601, 606)
        with override(inactive):
            assert bpy.ops.screen.area_split(direction='VERTICAL', factor=.5) == {'FINISHED'}
        print('PASS Playback keeps the initiating range across focus/editor changes without stale pointers', flush=True)
        return advance(.4)
    if phase == 4:
        copied = [area for area in areas() if bounds(area) == (601, 606)]
        assert len(copied) == 2
        copied[0].spaces.active.timeline_start = 0
        copied[0].spaces.active.timeline_end = 0
        assert bounds(copied[0]) == (0, 0) and bounds(copied[1]) == (601, 606)
        state['saved'] = sorted(bounds(area) for area in areas())
        bpy.context.preferences.filepaths.save_version = 0
        with override(areas()[0]):
            assert bpy.ops.wm.save_as_mainfile(filepath=str(fixture / 'video-ranges.blui'), check_existing=False) == {'FINISHED'}
        state['filepath'] = bpy.data.filepath
        print('PASS Native editor copies inherit bounds but remain independently editable, including valid 0..0', flush=True)
        return advance(.2)
    if phase == 5:
        state['phase'] += 1
        bpy.ops.wm.open_mainfile(filepath=state['filepath'])
        return .5
    if phase == 6:
        assert sorted(bounds(area) for area in areas()) == state['saved']
        assert scene_bounds() == state['global']
        strip = bpy.context.scene.sequence_editor.sequences.get(state['strip'][0])
        assert strip and (strip.name, strip.frame_start, strip.frame_final_duration) == state['strip']
        print('PASS Native project reload retains per-editor ranges and leaves video contents untouched', flush=True)
        if legacy.is_file():
            state['phase'] += 1
            bpy.ops.wm.open_mainfile(filepath=str(legacy))
            return .4
        print('SKIP Legacy packaged startup not present:', legacy, flush=True)
        state['phase'] = 9
        return .1
    if phase == 7:
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 37, 57
        window().workspace = bpy.data.workspaces['Video']
        return advance(.5)
    if phase == 8:
        videos = areas()
        assert videos and all(bounds(area) == (37, 57) for area in videos), [bounds(area) for area in videos]
        bpy.context.scene.frame_end = 200
        assert all(bounds(area) == (37, 57) for area in videos)
        print('PASS Older SDNA initializes once from its owning Scene and stops following global changes', flush=True)
        return advance(.1)
    if record_frame in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(record_frame)
    print('check_video_editor_ranges: PASS', fixture, flush=True)
    sys.stdout.flush()
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
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.5, persistent=True)
