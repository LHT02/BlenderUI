# SPDX-License-Identifier: GPL-2.0-or-later
"""Moving/detaching console editors must keep the actual interpreter namespace."""
import os
import sys
import time
import bpy
import console_python
from bl_ui import space_filebrowser_shell

state = {'step': 0, 'started': time.monotonic()}


def context(window, area=None):
    area = area or window.screen.areas[0]
    return bpy.context.temp_override(window=window, area=area,
        region=next(region for region in area.regions if region.type == 'WINDOW'))


def step():
    if time.monotonic() - state['started'] > 25:
        raise TimeoutError('Console runtime move timed out')
    n = state['step']
    if n == 0:
        space_filebrowser_shell.unregister()
        state['root'] = bpy.context.window_manager.windows[0]
        before = {window.as_pointer() for window in bpy.context.window_manager.windows}
        with context(state['root']):
            bpy.ops.wm.window_new()
        source = next(window for window in bpy.context.window_manager.windows if window.as_pointer() not in before)
        source.screen.areas[0].type = 'CONSOLE'
        state.update(source=source, source_id=source.as_pointer())
        delay = .4
    elif n == 1:
        with context(state['source']):
            state['region_id'] = bpy.context.region.as_pointer()
            state['space_id'] = bpy.context.space_data.as_pointer()
            console = console_python.get_console(hash(bpy.context.region))[0]
            console.locals['blui_runtime_fixture'] = {'value': 123456}
            state['console'] = console
            bpy.ops.screen.area_dock(source_window=str(state['source_id']),
                source_area=str(bpy.context.area.as_pointer()), source_space=str(state['space_id']),
                target_window=str(state['root'].as_pointer()),
                target_area=str(state['root'].screen.areas[0].as_pointer()), dock_target='LEFT', factor=.3)
        delay = .4
    elif n == 2:
        assert state['source_id'] not in {window.as_pointer() for window in bpy.context.window_manager.windows}
        area = next(area for area in state['root'].screen.areas if area.type == 'CONSOLE')
        with context(state['root'], area):
            assert bpy.context.region.as_pointer() == state['region_id']
            assert console_python.get_console(hash(bpy.context.region))[0] is state['console']
            assert state['console'].locals['blui_runtime_fixture']['value'] == 123456
            before = {window.as_pointer() for window in bpy.context.window_manager.windows}
            bpy.ops.screen.area_detach(cursor=(state['root'].width + 50, 300))
        state['detached'] = next(window for window in bpy.context.window_manager.windows if window.as_pointer() not in before)
        delay = .4
    else:
        with context(state['detached']):
            assert bpy.context.region.as_pointer() == state['region_id']
            assert bpy.context.space_data.as_pointer() == state['space_id']
            assert console_python.get_console(hash(bpy.context.region))[0] is state['console']
            assert state['console'].locals['blui_runtime_fixture']['value'] == 123456
        print('PASS Dock and detach preserve console region, editor identity, interpreter and variables', flush=True)
        print('check_docking45_console: PASS', flush=True)
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
