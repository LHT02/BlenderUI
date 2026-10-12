# SPDX-License-Identifier: GPL-2.0-or-later
"""Real corner mouse events dock into a different OS window with Ctrl snapping."""
import os
from pathlib import Path
import sys
import time
import ctypes as c
from ctypes import wintypes as w
import bpy
from bl_ui import space_filebrowser_shell

state = {'step': 0, 'started': time.monotonic()}


def place_fixture_window(source):
    # Position only this QA process's newly-created window. Never touch user apps.
    user = c.WinDLL('user32')
    user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
    user.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    matches, targets = [], []
    def visit(handle, _parameter):
        pid, rect = w.DWORD(), w.RECT()
        user.GetWindowThreadProcessId(handle, c.byref(pid))
        if pid.value == os.getpid() and user.GetClientRect(handle, c.byref(rect)):
            if rect.right == source.width and rect.bottom == source.height:
                matches.append(handle)
            if rect.right == state['target'].width and rect.bottom == state['target'].height:
                targets.append(handle)
        return True
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.EnumWindows(callback_type(visit), 0)
    assert len(matches) == 1, 'Could not identify the fixture source HWND uniquely'
    assert len(targets) == 1, 'Could not identify the fixture target HWND uniquely'
    user.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
    # Make the fixture target, then source, visible above unrelated user windows.
    assert user.SetWindowPos(targets[0], None, 0, 0, 0, 0, 0x13)
    assert user.SetWindowPos(matches[0], None, state['target'].x + 300, 200, 700, 550, 0x10)


def override(window, area):
    return bpy.context.temp_override(window=window, area=area,
        region=next(region for region in area.regions if region.type == 'WINDOW'))


def event(kind, value, point, **modifiers):
    state['source'].event_simulate(type=kind, value=value, x=point[0], y=point[1], **modifiers)


def step():
    if time.monotonic() - state['started'] > 25:
        raise TimeoutError('Cross-window corner drag timed out')
    n = state['step']
    if n == 0:
        space_filebrowser_shell.unregister()
        target = bpy.context.window_manager.windows[0]
        state.update(target=target, target_area=target.screen.areas[0])
        workspace = next(workspace for workspace in bpy.data.workspaces
            if any(area.type == 'TEXT_EDITOR' for screen in workspace.screens for area in screen.areas))
        before = {window.as_pointer() for window in bpy.context.window_manager.windows}
        with override(target, state['target_area']):
            bpy.ops.wm.window_new(workspace=workspace.name)
        source = next(window for window in bpy.context.window_manager.windows if window.as_pointer() not in before)
        area = source.screen.areas[0]
        area.type = 'TEXT_EDITOR'
        text = bpy.data.texts.new('native-cross-window-buffer')
        text.write('unsaved content survives real cross-window docking')
        area.spaces.active.text = text
        state.update(source=source, source_id=source.as_pointer(), source_area=area,
                     text=text, space=area.spaces.active.as_pointer())
        delay = .5
    elif n == 1:
        place_fixture_window(state['source'])
        state['step'] += 1
        return .5
    elif n == 2:
        source, target, area = state['source'], state['target'], state['target_area']
        choices = [(area.x + 5, area.y + area.height // 2),
                   (area.x + area.width - 5, area.y + area.height // 2),
                   (area.x + area.width // 2, area.y + 5),
                   (area.x + area.width // 2, area.y + area.height - 5)]
        drop = next(((x + target.x - source.x, y + target.y - source.y) for x, y in choices
                     if not (source.x <= x + target.x < source.x + source.width and
                             source.y <= y + target.y < source.y + source.height)), None)
        assert drop, 'Factory new window leaves no target edge exposed'
        source_area = state['source_area']
        state.update(drop=drop, point=(source_area.x + source_area.width - 3,
                                      source_area.y + source_area.height - 3))
        print('DRAG GEOMETRY', (source.x, source.y, source.width, source.height),
              (target.x, target.y, target.width, target.height), drop, flush=True)
        event('MOUSEMOVE', 'NOTHING', state['point'])
        event('LEFTMOUSE', 'PRESS', state['point'])
        delay = .2
    elif n == 3:
        event('MOUSEMOVE', 'NOTHING', state['drop'], ctrl=True, alt=True)
        delay = .4
    elif n == 4:
        with override(state['target'], state['target_area']):
            bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[3] / 'build/dock-target-preview.png'))
        event('LEFTMOUSE', 'RELEASE', state['drop'], ctrl=True, alt=True)
        delay = .5
    else:
        if state['source_id'] in {window.as_pointer() for window in bpy.context.window_manager.windows}:
            state.setdefault('waiting', time.monotonic())
            if time.monotonic() - state['waiting'] < 2:
                return .05
        assert state['source_id'] not in {window.as_pointer() for window in bpy.context.window_manager.windows}
        assert len(state['target'].screen.areas) == 2
        moved = next(area for area in state['target'].screen.areas if area.type == 'TEXT_EDITOR')
        assert moved.spaces.active.as_pointer() == state['space']
        assert moved.spaces.active.text == state['text']
        print('PASS Real corner mouse drag docks into another OS window, preserves editor identity and buffer', flush=True)
        print('check_docking45_drag: PASS', flush=True)
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
