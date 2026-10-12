# SPDX-License-Identifier: GPL-2.0-or-later
"""The unified corner gesture retains Ctrl swap and Shift duplicate behavior."""
import os
import sys
import time
import bpy
from bl_ui import space_filebrowser_shell

state = {'step': 0, 'started': time.monotonic()}


def context(area=None):
    area = area or state['window'].screen.areas[0]
    return bpy.context.temp_override(window=state['window'], area=area,
        region=next(region for region in area.regions if region.type == 'WINDOW'))


def event(kind, value, point, **modifiers):
    state['window'].event_simulate(type=kind, value=value, x=point[0], y=point[1], **modifiers)


def step():
    if time.monotonic() - state['started'] > 25:
        raise TimeoutError('Modifier gestures timed out')
    n = state['step']
    if n == 0:
        space_filebrowser_shell.unregister()
        state['window'] = bpy.context.window_manager.windows[0]
        with context():
            bpy.ops.screen.area_split(direction='VERTICAL', factor=.5)
        delay = .4
    elif n == 1:
        left, right = sorted(state['window'].screen.areas, key=lambda area: area.x)
        state.update(left=left, right=right)
        for area, name in ((left, 'modifier-left'), (right, 'modifier-right')):
            area.type = 'TEXT_EDITOR'
            text = bpy.data.texts.new(name)
            text.write('buffer ' + name)
            area.spaces.active.text = text
        state.update(left_space=left.spaces.active.as_pointer(), right_space=right.spaces.active.as_pointer(),
                     point=(left.x + 2, left.y + 2),
                     drop=(right.x + right.width // 2, right.y + right.height // 2))
        delay = .3
    elif n == 2:
        event('LEFT_CTRL', 'PRESS', state['point'], ctrl=True)
        event('MOUSEMOVE', 'NOTHING', state['point'], ctrl=True)
        event('LEFTMOUSE', 'PRESS', state['point'], ctrl=True)
        delay = .2
    elif n == 3:
        event('MOUSEMOVE', 'NOTHING', state['drop'], ctrl=True)
        delay = .2
    elif n == 4:
        event('MOUSEMOVE', 'NOTHING', state['drop'], ctrl=True)
        event('LEFTMOUSE', 'RELEASE', state['drop'], ctrl=True)
        delay = .4
    elif n == 5:
        event('LEFT_CTRL', 'RELEASE', state['point'])
        assert len(state['window'].screen.areas) == 2
        assert state['left'].spaces.active.as_pointer() == state['right_space']
        assert state['right'].spaces.active.as_pointer() == state['left_space']
        assert state['left'].spaces.active.text.name == 'modifier-right'
        print('PASS Ctrl corner swap moves actual editor identities and keeps both buffers', flush=True)
        with context(state['right']):
            bpy.ops.screen.area_close(confirmed=True)
        delay = .3
    elif n == 6:
        area = state['window'].screen.areas[0]
        state.update(original=area.spaces.active.as_pointer(), text=area.spaces.active.text,
                     before={window.as_pointer() for window in bpy.context.window_manager.windows},
                     point=(area.x + area.width - 3, area.y + area.height - 3),
                     drop=(area.x + area.width - 80, area.y + area.height - 80))
        event('LEFT_SHIFT', 'PRESS', state['point'], shift=True)
        event('MOUSEMOVE', 'NOTHING', state['point'], shift=True)
        event('LEFTMOUSE', 'PRESS', state['point'], shift=True)
        delay = .2
    elif n == 7:
        event('MOUSEMOVE', 'NOTHING', state['drop'], shift=True)
        delay = .3
    elif n == 8:
        event('LEFTMOUSE', 'RELEASE', state['drop'], shift=True)
        delay = .4
    else:
        event('LEFT_SHIFT', 'RELEASE', state['drop'])
        new = [window for window in bpy.context.window_manager.windows if window.as_pointer() not in state['before']]
        assert len(new) == 1
        assert state['window'] in list(bpy.context.window_manager.windows), 'Shift duplicate removed the source'
        assert new[0].screen.areas[0].spaces.active.text == state['text']
        assert new[0].screen.areas[0].spaces.active.as_pointer() != state['original']
        print('PASS Shift corner duplicates independently and retains the original window', flush=True)
        print('check_docking45_modifiers: PASS', flush=True)
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
