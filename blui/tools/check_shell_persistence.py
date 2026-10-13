# SPDX-License-Identifier: GPL-2.0-or-later
"""Own-process save/reload of auxiliary windows; no system-bar changes or app launches.

Run serially with --factory-startup --python-exit-code 1 --python this file.
Only strings/counts survive loading Main; every Window/Screen lookup is fresh.
"""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
import bpy
from blui_desktop import native_windows, runtime, session

session.disable_for_tests = True
# This fixture creates role windows directly, not through the hover controller.
# Stop its idle-popup service; otherwise a deliberately unhovered preview is
# correctly closed before the persistence assertion can inspect/save it.
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
fixture = Path(tempfile.mkdtemp(prefix='blui_shell_save_qa_'))
(fixture / 'config').mkdir()
os.environ['BLENDER_USER_CONFIG'] = str(fixture / 'config')
os.environ['BLUI_DESKTOP_CONFIG'] = str(fixture / 'config')
state = {'phase': 0, 'cycle': 0, 'started': time.monotonic(), 'due': 0, 'names': set()}
user = native_windows._api()


def windows(role=None):
    return [window for window in bpy.context.window_manager.windows
            if role is None or window.blui_shell_role == role]


def execute(window, name, **props):
    if window is None:
        result = getattr(bpy.ops.wm, name)(**props)
    else:
        area = next(iter(window.screen.areas), None)
        region = next((region for region in area.regions if region.type == 'WINDOW'), None) if area else None
        with bpy.context.temp_override(window=window, area=area, region=region):
            result = getattr(bpy.ops.wm, name)(**props)
    assert result == {'FINISHED'}, (name, result)


def create_roles():
    source = windows('NORMAL')[0]
    for role, width, height in (('TASKBAR', 800, 48), ('STARTMENU', 600, 680),
                                ('TASK_CHOOSER', 440, 400), ('TASK_PREVIEW', 500, 180)):
        execute(source, 'blui_shell_window_create', role=role, width=width, height=height)


def save(path):
    execute(windows()[0], 'save_as_mainfile', filepath=str(path), check_existing=False, copy=True)
    assert path.is_file()


def load(path):
    # Loading replaces Main and its areas; never retain an override restoration
    # stack containing the soon-to-be-freed Window/Area/Region across that call.
    assert bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=True) == {'FINISHED'}


def assert_normal(window):
    handle = int(window.blui_native_handle)
    identity = native_windows._identity(user, handle)
    assert identity and identity[0] == os.getpid()
    assert window.blui_shell_role == 'NORMAL' and window.height > 200
    assert user.GetWindowLongPtrW(handle, -16) & 0x00C00000, 'normal window lost its caption'
    assert not user.GetWindowLongPtrW(handle, -20) & 0x08000000, 'normal window inherited NOACTIVATE'


def step():
    if time.monotonic() - state['started'] > 55:
        raise TimeoutError('Shell save/reload regression timed out')
    if time.monotonic() < state['due']:
        return .05
    phase = state['phase']
    if phase == 0:
        # Ordinary INFO is intentionally not a shell role and must survive cleanup.
        source = windows('NORMAL')[0]
        source.screen.areas[0].type = 'INFO'
        state['baseline'] = len(bpy.data.screens)
        state['normal_info'] = source.screen.name
        create_roles()
        state['phase'], state['due'] = 1, time.monotonic() + .5
    elif phase == 1:
        assert all(windows(role) for role in ('TASKBAR', 'STARTMENU', 'TASK_CHOOSER', 'TASK_PREVIEW'))
        state['names'] = {window.screen.name for window in windows() if window.blui_shell_role != 'NORMAL'}
        path = fixture / 'with-shell.blend'
        save(path)
        state['phase'], state['due'] = 2, time.monotonic() + .3
        load(path)
    elif phase == 2:
        assert windows() and all(window.blui_shell_role == 'NORMAL' for window in windows())
        assert not state['names'] & {screen.name for screen in bpy.data.screens}, 'orphan shell screens survived load'
        assert len(bpy.data.screens) == state['baseline'], 'private shell layouts accumulated'
        assert bpy.data.screens.get(state['normal_info']) is not None, 'ordinary INFO screen was incorrectly deleted'
        assert_normal(windows('NORMAL')[0])
        state['cycle'] += 1
        if state['cycle'] < 3:
            create_roles()
            state['phase'], state['due'] = 1, time.monotonic() + .4
        else:
            print('PASS Three role-window save/reload cycles retain ordinary INFO but remove all helper layouts', flush=True)
            source = windows('NORMAL')[0]
            execute(source, 'blui_shell_window_create', role='TASKBAR', width=800, height=48)
            for window in list(windows('NORMAL')):
                execute(window, 'window_close', force_close=True)
            assert windows() and all(window.blui_is_taskbar for window in windows())
            path = fixture / 'only-taskbar.blend'
            save(path)
            state['phase'], state['due'] = 3, time.monotonic() + .4
            load(path)
    elif phase == 3:
        assert all(window.blui_shell_role == 'NORMAL' for window in windows())
        before = {window.as_pointer() for window in windows()}
        execute(windows()[0] if windows() else None, 'window_new', workspace='Files')
        added = [window for window in windows() if window.as_pointer() not in before]
        assert len(added) == 1
        assert_normal(added[0])
        assert added[0].screen.areas[0].type == 'INFO', 'saved ordinary component should remain unchanged'
        assert len({window.screen.as_pointer() for window in windows()}) == len(windows())
        assert not any(screen.name.startswith('BLUI Shell UI') for screen in bpy.data.screens)
        print('check_shell_persistence: PASS (only-taskbar save/read is non-crashing, no helper HWND reused, normal sizing)', flush=True)
        os._exit(0)
    return .05


def guarded():
    try:
        return step()
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.7, persistent=True)
