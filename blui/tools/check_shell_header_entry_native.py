# SPDX-License-Identifier: GPL-2.0-or-later
"""ROOT ONLY: disposable native shell header/azone/RNA/resize regression.

Factory startup and isolated CONFIG required. Never enables desktop hosting,
AppBar, original taskbar hiding, system tray providers or external actions.
Only fixture-owned windows are resized/closed; no global input or preference save.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import sys
import time
import traceback
import bpy
from blui_desktop import native_windows, runtime, session

assert os.environ.get('BLUI_SHELL_HEADER_QA') == '1', 'Explicit private GUI QA opt-in required'
session.disable_for_tests = True
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
user = native_windows._api()
user.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
user.SetWindowPos.restype = w.BOOL
normal = next(window for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL')
normal_key = normal.as_pointer(), normal.blui_native_handle
owned = []
state = {'phase': 0, 'started': time.monotonic(), 'points': {}}
output = Path('D:/BlenderUI/build/shell-header-entry-qa')
output.mkdir(exist_ok=True)


def fresh(token):
    window = next(window for window in bpy.context.window_manager.windows
                  if (window.as_pointer(), window.blui_native_handle) == token)
    assert native_windows._identity(user, int(token[1]))[0] == os.getpid()
    area = max(window.screen.areas, key=lambda area: area.width * area.height)
    region = next(region for region in area.regions if region.type == 'WINDOW')
    header = next(region for region in area.regions if region.type == 'HEADER')
    return window, area, region, header


def hidden(window, area):
    assert not area.spaces.active.show_region_header, window.blui_shell_role
    header = next(region for region in area.regions if region.type == 'HEADER')
    assert header.height <= 1, (window.blui_shell_role, header.height)


def finish(code):
    # No helper transactions are in use; close only precise fixture-owned windows.
    for token in reversed(owned):
        try:
            window, _area, _region, _header = fresh(token)
            with bpy.context.temp_override(window=window):
                bpy.ops.wm.window_close(force_close=True)
        except (StopIteration, ReferenceError):
            pass
    assert fresh(normal_key)[0].blui_shell_role == 'NORMAL'
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def tick():
    try:
        assert time.monotonic() - state['started'] < 30, 'Native header QA timed out'
        phase = state['phase']
        if phase == 0:
            for role in ('TASKBAR', 'STARTMENU', 'TASK_CHOOSER', 'TASK_PREVIEW', 'DESKTOP'):
                before = {window.as_pointer() for window in bpy.context.window_manager.windows}
                with bpy.context.temp_override(window=normal):
                    assert bpy.ops.wm.blui_shell_window_create(role=role, width=720, height=320) == {'FINISHED'}
                window = next(window for window in bpy.context.window_manager.windows
                              if window.as_pointer() not in before)
                owned.append((window.as_pointer(), window.blui_native_handle))
            state['phase'] = 1
            return .3
        if phase == 1:
            for token in owned:
                window, area, region, _header = fresh(token)
                if window.blui_shell_role == 'DESKTOP':
                    continue
                hidden(window, area)
                with bpy.context.temp_override(window=window, area=area, region=region):
                    assert bpy.ops.screen.region_toggle(region_type='HEADER') == {'CANCELLED'}
                    area.spaces.active.show_region_header = True  # Direct RNA bypass must not reopen it.
                hidden(window, area)
                assert user.SetWindowPos(int(token[1]), None, 0, 0, 760, 350, 2 | 4 | 16)
            state['phase'] = 2
            return .3
        if phase == 2:
            for token in owned:
                window, area, _region, header = fresh(token)
                if window.blui_shell_role == 'DESKTOP':
                    continue
                hidden(window, area)
                # Same center used by the old header tab: 1.5 * 0.7 * 20px unit.
                point = (area.x + area.width - 22,
                         area.y + 4 if header.y < area.y + area.height / 2 else area.y + area.height - 4)
                state['points'][token] = point
                window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=point[0], y=point[1])
            state['phase'] = 3
            return .3
        if phase == 3:
            for token in owned:
                window, area, region, _header = fresh(token)
                if window.blui_shell_role == 'DESKTOP':
                    continue
                with bpy.context.temp_override(window=window, area=area, region=region):
                    # Scrollbar azones intentionally survive. Their invoke is
                    # PASS_THROUGH, unlike a header azone (FINISHED/modal or the
                    # stale-header CANCELLED guard). Do not demand a no-scroll UI.
                    if bpy.ops.screen.actionzone.poll():
                        result = bpy.ops.screen.actionzone('INVOKE_DEFAULT', modifier=0)
                        assert result == {'PASS_THROUGH'}, ('Old header target survived', window.blui_shell_role, result)
                    assert bpy.ops.screen.screenshot(filepath=str(output / (window.blui_shell_role + '.png'))) == {'FINISHED'}
                hidden(window, area)
                print('PASS', window.blui_shell_role, 'header/RNA locked, resize rebuilt, old arrow not hit-testable', flush=True)
            for token in (normal_key, owned[-1]):
                window, area, region, _header = fresh(token)
                space = area.spaces.active
                with bpy.context.temp_override(window=window, area=area, region=region):
                    space.show_region_header = False
                    assert bpy.ops.screen.region_toggle(region_type='HEADER') == {'FINISHED'}
                    assert space.show_region_header
                    space.show_region_header = False
                assert not space.show_region_header
                print('PASS', window.blui_shell_role, 'normal header controls preserved', flush=True)
            window, area, region, _header = fresh(normal_key)
            with bpy.context.temp_override(window=window, area=area, region=region):
                assert bpy.ops.screen.screenshot(filepath=str(output / 'NORMAL.png')) == {'FINISHED'}
            print('check_shell_header_entry_native: PASS', flush=True)
            finish(0)
        return .05
    except Exception:
        traceback.print_exc()
        finish(1)


bpy.app.timers.register(tick, first_interval=.5)
