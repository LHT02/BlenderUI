# SPDX-License-Identifier: GPL-2.0-or-later
"""Real native Start-window interaction QA; programs are indexed but NEVER launched.

Run only by the primary agent, serially with other GUI checks:
BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python ...
The test owns its Start/taskbar windows and isolated CONFIG. It does not register
an AppBar, hide the original taskbar, execute power actions or alter the clipboard.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
import bpy
from blui_desktop import start_menu, start_menu_model as schema, start_menu_ui

temporary = tempfile.TemporaryDirectory(prefix='blui_start_ui_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
source = bpy.context.window
started = time.monotonic()
phase = 0
due = 0
app = None
bar = None
main_pointer = source.as_pointer()
main_screen = source.screen.as_pointer()
menu_pointer = None


def menus():
    return [window for window in bpy.context.window_manager.windows if window.blui_shell_role == 'STARTMENU']


def invoke(window, name, **kwargs):
    with bpy.context.temp_override(window=window):
        result = getattr(bpy.ops.wm, name)('INVOKE_DEFAULT', **kwargs)
    assert result == {'FINISHED'}, (name, result)


def finish(code):
    start_menu.close()
    temporary.cleanup()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def tick():
    global phase, due, app, bar, menu_pointer
    try:
        if time.monotonic() - started > 35:
            raise AssertionError('Start menu native QA timed out')
        if time.monotonic() < due:
            return .05
        if phase == 0:
            invoke(source, 'blui_start_menu')
            assert len(menus()) == 1
            menu = menus()[0]
            menu_pointer = menu.as_pointer()
            assert menu.screen.as_pointer() != main_screen
            assert menu.screen.areas[0].type == 'INFO'
            assert start_menu_ui.BLUI_PT_start_menu.poll(type('Context', (), {'window': menu})())
            phase, due = 1, time.monotonic() + .5
        elif phase == 1:
            value = start_menu.snapshot()
            if not value['loaded']:
                assert not value['error'], value['error']
                return .05
            assert value['rows'], 'Readonly Programs fixture should find installed Windows apps'
            menu = menus()[0]
            assert menu.width >= 450 and menu.height >= 500, 'Start menu must not be clipped to a thin taskbar'
            from blui_desktop import native_windows
            assert not native_windows._api().GetWindowLongPtrW(int(menu.blui_native_handle), -16) & 0x00C00000
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from qa_shell_pixels import verify
            verify(menu, 'start-menu')
            settings = bpy.context.window_manager.blui_start_menu_settings
            settings.query = 'BLUI QA input is not a command && shutdown /s'
            assert start_menu_ui._rows(settings, value) == []
            app = value['rows'][0]
            settings.query = app['name']
            assert app['id'] in {row['id'] for row in start_menu_ui._rows(settings, value)}
            settings.query = ''
            with bpy.context.temp_override(window=menu):
                assert bpy.ops.wm.blui_start_pin(app_id=app['id']) == {'FINISHED'}
            assert app['id'] in start_menu.snapshot()['pins']
            # Opening from a normal document window focuses/reuses the menu, never creates a duplicate.
            invoke(source, 'blui_start_menu')
            assert len(menus()) == 1 and menus()[0].as_pointer() == menu_pointer
            phase, due = 2, time.monotonic() + .5
        elif phase == 2:
            if not (Path(temporary.name) / 'start-menu.json').exists() or start_menu._dirty:
                return .05
            from blui_desktop import start_menu_backend
            saved = start_menu_backend.load_state(temporary.name)
            assert app['id'] in saved['pins']
            assert saved['recent'] == [], 'No application should have been launched by this test'
            before = {window.as_pointer() for window in bpy.context.window_manager.windows}
            with bpy.context.temp_override(window=source):
                assert bpy.ops.wm.blui_shell_window_create(role='TASKBAR', width=720, height=48) == {'FINISHED'}
            bar = next(window for window in bpy.context.window_manager.windows if window.as_pointer() not in before)
            assert bar.blui_is_taskbar
            if not menus():
                # Windows can move foreground to the driving app while async pin
                # persistence completes. Establish the open-state toggle precondition.
                invoke(source, 'blui_start_menu')
            assert len(menus()) == 1
            invoke(bar, 'blui_start_menu')
            assert not menus(), 'Second taskbar Start click should toggle closed'
            phase, due = 3, time.monotonic() + .3
        elif phase == 3:
            invoke(bar, 'blui_start_menu')
            assert len(menus()) == 1
            phase, due = 4, time.monotonic() + .5
        elif phase == 4:
            menu = menus()[0]
            menu.event_simulate(type='MOUSEMOVE', value='NOTHING', x=120, y=120)
            menu.event_simulate(type='ESC', value='PRESS', x=120, y=120)
            menu.event_simulate(type='ESC', value='RELEASE', x=120, y=120)
            phase, due = 5, time.monotonic() + .5
        else:
            assert not menus(), 'ESC did not close the independent Start menu'
            assert any(window.as_pointer() == main_pointer for window in bpy.context.window_manager.windows)
            assert source.screen.as_pointer() == main_screen, 'Opening Start must not alter the original layout'
            assert bar.blui_shell_role == 'TASKBAR', 'ESC must not close or mutate the taskbar role'
            with bpy.context.temp_override(window=bar):
                assert not bpy.ops.wm.blui_shell_popup_close.poll(), 'TASKBAR must reject popup-close poll'
                bpy.ops.wm.window_close(force_close=True)
            print('PASS: native Start role, independent screen/size, readonly indexed search, pin/atomic-save, '
                  'normal-window reuse, taskbar toggle, real ESC release; zero app launches/power changes')
            finish(0)
        return .05
    except Exception:
        traceback.print_exc()
        finish(1)


bpy.app.timers.register(tick, first_interval=.5)
