# SPDX-License-Identifier: GPL-2.0-or-later
"""Real native corner events, including a provisional split and Escape cancellation."""
import os
import sys
import time
import bpy
from bl_ui import space_filebrowser_shell

state = {'corner': 0, 'phase': 0, 'started': time.monotonic()}


def event(kind, value, xy):
    state['window'].event_simulate(type=kind, value=value, x=xy[0], y=xy[1])


def step():
    if time.monotonic() - state['started'] > 30:
        raise TimeoutError('Corner drag regression timed out')
    phase, corner = state['phase'], state['corner']
    if phase == 0:
        space_filebrowser_shell.unregister()
        window = bpy.context.window_manager.windows[0]
        area = next(iter(window.screen.areas))
        area.type = 'TEXT_EDITOR'
        text = state.get('text') or bpy.data.texts.new('corner-detach-buffer')
        if not state.get('text'):
            text.write('unsaved buffer survives every corner drag')
        area.spaces.active.text = text
        state.update(window=window, text=text,
                     before={w.as_pointer() for w in bpy.context.window_manager.windows})
        right, top = bool(corner & 1), bool(corner & 2)
        point = (area.x + area.width - 3 if right else area.x + 2,
                 area.y + area.height - 3 if top else area.y + 2)
        outside = (window.width + 50 if right else -50, window.height + 50 if top else -50)
        state.update(point=point, outside=outside)
        delay = 0.4
    elif phase == 1:
        event('MOUSEMOVE', 'NOTHING', state['point'])
        event('LEFTMOUSE', 'PRESS', state['point'])
        delay = 0.2
    elif phase == 2:
        if corner == 3:
            event('MOUSEMOVE', 'NOTHING', (state['point'][0] - 80, state['point'][1] - 80))
        else:
            event('MOUSEMOVE', 'NOTHING', state['outside'])
        delay = 0.3
    elif phase == 3:
        event('MOUSEMOVE', 'NOTHING', state['outside'])
        delay = 0.2
    elif phase == 4:
        if corner == 4:
            event('ESC', 'PRESS', state['outside'])
            event('ESC', 'RELEASE', state['outside'])
        else:
            event('LEFTMOUSE', 'RELEASE', state['outside'])
        delay = 0.5
    elif phase == 5:
        windows = list(bpy.context.window_manager.windows)
        if corner == 4:
            assert {w.as_pointer() for w in windows} == state['before']
            print('PASS Escape cancels out-of-window drag without losing the document', flush=True)
            print('check_corner_detach: PASS', flush=True)
            os._exit(0)
        new = [w for w in windows if w.as_pointer() not in state['before']]
        assert len(new) == 1, 'Corner %d did not create exactly one window' % corner
        assert len(windows) == 1, 'Source single-editor window was duplicated instead of moved'
        assert new[0].screen.areas[0].spaces.active.text == state['text']
        assert new[0].screen.areas[0].spaces.active.text.as_string() == 'unsaved buffer survives every corner drag'
        assert new[0].parent is None
        print('PASS Native corner', corner, '(provisional split first)' if corner == 3 else '', flush=True)
        state['corner'] += 1
        state['phase'] = 0
        return 0.2
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


bpy.app.timers.register(guarded, first_interval=0.5)
