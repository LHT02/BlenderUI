# SPDX-License-Identifier: GPL-2.0-or-later
"""Serial, OWN-PID shell regression; only the primary agent runs this fixture.

BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python ...
No external app launches, notification broadcasts, system taskbar hiding, AppBar
reservation, foreign callbacks/window actions or real cursor movement. DWM rows
prove successful live registrations; GL screenshots do NOT capture DWM compositing.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest import mock
import bpy
from blui_desktop import (icon_cache, native_windows, runtime, session, shell_hover,
    start_menu, start_menu_contents as contents, start_menu_model as schema,
    taskbar_actions, taskbar_windows, window_placement)

temporary = tempfile.TemporaryDirectory(prefix='blui_shell_redesign_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
session.disable_for_tests = True
source_pointer, source_handle = bpy.context.window.as_pointer(), bpy.context.window.blui_native_handle
source_token = (source_pointer, source_handle)
source_screen = bpy.context.window.screen.as_pointer()
workspaces = {workspace.name for workspace in bpy.data.workspaces}
started = time.monotonic()
state = {'phase': 0, 'due': 0, 'bar': None, 'second': None, 'point': None,
         'drawn': set(), 'patches': [], 'probes': [], 'start': None, 'focus_hold': False}
user = native_windows._api()


def token(window):
    return window.as_pointer(), window.blui_native_handle


def fresh(identity, role=None):
    """Never dereference RNA retained across a timer or a native window close."""
    value = next((window for window in bpy.context.window_manager.windows
                  if token(window) == identity and (role is None or window.blui_shell_role == role)), None)
    assert value is not None, ('Owned QA window closed or changed', identity, role, state['phase'])
    return value


def patch(*args, **kwargs):
    value = mock.patch.object(*args, **kwargs)
    state['patches'].append(value)
    return value.start()


def forbidden(*_args, **_kwargs):
    raise AssertionError('This fixture must not launch an application or system action')


def own_row(window):
    handle = int(window.blui_native_handle)
    identity = native_windows._identity(user, handle)
    assert identity and identity[0] == os.getpid(), 'Only OWN PID tasks may enter the QA DWM group'
    pid, thread, created, name = identity
    return {'handle': str(handle), 'pid': pid, 'thread_id': thread, 'process_started': created,
            'window_class': name, 'title': 'QA owned ' + str(window.as_pointer()),
            'actionable': True, 'active': False, 'minimized': False,
            **native_windows._metadata(pid), 'monitor': taskbar_windows.device(fresh(state['bar'], 'TASKBAR'))}


def region(window):
    return next(item for item in window.screen.areas[0].regions if item.type == 'WINDOW')


def execute(window, name, *, invoke=False, **properties):
    with bpy.context.temp_override(window=window, area=window.screen.areas[0], region=region(window)):
        result = getattr(bpy.ops.wm, name)(*(['INVOKE_DEFAULT'] if invoke else []), **properties)
    assert result == {'FINISHED'}, (name, result)


def move(window, point):
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=point[0], y=point[1])


def right_click(window, point):
    move(window, point)
    for value in ('PRESS', 'RELEASE'):
        window.event_simulate(type='RIGHTMOUSE', value=value, x=point[0], y=point[1])


def override_hovered(window):
    with bpy.context.temp_override(window=window, area=window.screen.areas[0], region=region(window)):
        value = getattr(bpy.context, 'blui_shell_hover_button', None)
        return (value.bl_rna.identifier, getattr(value, 'app_id', '')) if value else ('', '')


def absolute_point(window, point):
    rect = window_placement.bounds(window.blui_native_handle)['rect']
    return rect[0] + point[0], rect[3] - 1 - point[1]


def extent(window):
    view, item = region(window).view2d, region(window)
    low, high = view.region_to_view(0, 0), view.region_to_view(item.width, item.height)
    return abs(high[0] - low[0]), abs(high[1] - low[1])


def menu(kind):
    windows = taskbar_windows.role_windows('TASK_CHOOSER')
    assert len(windows) == 1, (kind, len(windows))
    value = windows[0]
    bar_window = fresh(state['bar'], 'TASKBAR')
    assert taskbar_windows.menu_state(value)['kind'] == kind
    assert value.height > 2 * bar_window.height, 'Context menu is constrained inside the thin bar'
    assert value.screen.as_pointer() != bar_window.screen.as_pointer()
    rect, bar = window_placement.bounds(value.blui_native_handle)['rect'], window_placement.bounds(bar_window.blui_native_handle)['rect']
    assert rect[3] <= bar[1] + 2, ('Menu must be above the taskbar', rect, bar)
    assert not user.GetWindowLongPtrW(int(value.blui_native_handle), -16) & 0x00c00000
    return value


def next_phase(value, delay=.3):
    state['phase'], state['due'] = value, time.monotonic() + delay


def finish(code):
    contents.BLUI_UL_start_programs.draw_item = state.get('draw_original', contents.BLUI_UL_start_programs.draw_item)
    shell_hover.close()
    for value in reversed(state['patches']):
        value.stop()
    start_menu.close()
    temporary.cleanup()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # Only this disposable QA PID; never saves quit.blend.


def tick():
    try:
        if time.monotonic() - started > 70:
            raise AssertionError(('Shell redesign QA timed out', state['phase']))
        if time.monotonic() < state['due']:
            return .05
        phase = state['phase']
        if phase == 0:
            patch(shell_hover, 'cursor', side_effect=lambda: state['point'])
            patch(start_menu, 'ensure', return_value=None)
            real_foreground = taskbar_windows.is_foreground
            def foreground(window):
                if state['focus_hold'] and window.blui_shell_role == 'STARTMENU' and token(window) == state['start']:
                    assert native_windows._identity(user, int(window.blui_native_handle))[0] == os.getpid()
                    return True  # Read-only fixture simulation; no native focus/write bypass.
                return real_foreground(window)
            patch(taskbar_windows, 'is_foreground', side_effect=foreground)
            for owner, method in ((start_menu, 'launch'), (start_menu, 'system_action'),
                                  (start_menu, 'open_location'), (taskbar_actions, 'launch_group')):
                patch(owner, method, side_effect=forbidden)
            start_menu.close()
            fake_rows = []
            for index in range(80):
                relative = f'QA Item {index:03d}.lnk'
                fake_rows.append(schema.program({'id': schema.app_id('user', relative), 'source': 'user',
                    'relative': relative, 'path': str(Path(temporary.name) / relative),
                    'name': f'QA Item {index:03d}', 'group': '',
                    'signature': {'mtime_ns': 0, 'size': 0, 'device': 0, 'inode': 0}}))
            start_menu._rows, start_menu._loaded = fake_rows, True
            start_menu._directory = temporary.name
            state['fake_rows'] = fake_rows
            original = state['draw_original'] = contents.BLUI_UL_start_programs.draw_item
            def draw(self, context, layout, data, item, icon, active_data, active_propname):
                if item.kind == 'APP':
                    state['drawn'].add(item.app_id)
                return original(self, context, layout, data, item, icon, active_data, active_propname)
            contents.BLUI_UL_start_programs.draw_item = draw
            execute(fresh(source_token, 'NORMAL'), 'blui_taskbar_open', all_displays=False)
            next_phase(1)
        elif phase == 1:
            bars = taskbar_windows.role_windows('TASKBAR')
            if not bars:
                return .05
            assert len(bars) == 1
            bar = bars[0]
            state['bar'] = token(bar)
            execute(bar, 'blui_taskbar_layout', mode='CENTER')
            before = {window.as_pointer() for window in bpy.context.window_manager.windows}
            execute(fresh(source_token, 'NORMAL'), 'window_new', workspace='Files')
            second = [window for window in bpy.context.window_manager.windows if window.as_pointer() not in before]
            assert len(second) == 1 and second[0].blui_shell_role == 'NORMAL'
            state['second'] = token(second[0])
            runtime._tasks = [own_row(fresh(source_token, 'NORMAL')), own_row(second[0])]
            runtime._last_tasks = time.monotonic() + 3600
            groups = taskbar_actions.current_groups(bar)
            assert len(groups) == 1 and len(groups[0]['tasks']) == 2
            state['group'] = groups[0]['key']
            icon_cache.application(groups[0])
            taskbar_windows.redraw()
            next_phase(2)
        elif phase == 2:
            bar = fresh(state['bar'], 'TASKBAR')
            groups = taskbar_actions.current_groups(bar)
            if not icon_cache.application(groups[0]):
                return .05
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from qa_shell_pixels import verify
            bounds = verify(bar, 'taskbar', large_taskbar_icons=True)
            state['app_point'] = ((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
            state['start_point'] = (round(24 * bpy.context.preferences.system.ui_scale), bar.height // 2)
            right_click(bar, state['app_point'])
            next_phase(3)
        elif phase == 3:
            popup = menu('TASK_CONTEXT')
            assert taskbar_windows.menu_state(popup)['key'] == state['group']
            from qa_shell_pixels import verify
            verify(popup, 'chooser')
            execute(popup, 'blui_shell_popup_close')
            right_click(fresh(state['bar'], 'TASKBAR'), state['start_point'])
            next_phase(4)
        elif phase == 4:
            popup = menu('START_CONTEXT')
            execute(popup, 'blui_shell_popup_close')
            state['point'] = absolute_point(fresh(state['bar'], 'TASKBAR'), state['app_point'])
            move(fresh(state['bar'], 'TASKBAR'), state['app_point'])
            next_phase(5, .4)
        elif phase == 5:
            shell_hover.tick()
            preview = shell_hover.preview_window()
            if preview is None:
                return .05
            assert preview.blui_shell_role == 'TASK_PREVIEW'
            assert preview.height > 2 * fresh(state['bar'], 'TASKBAR').height
            handle = int(preview.blui_native_handle)
            assert native_windows._identity(user, handle)[0] == os.getpid()
            assert user.GetWindowLongPtrW(handle, -20) & 0x08000000
            assert not user.GetWindowLongPtrW(handle, -16) & 0x00c00000
            rows = shell_hover._controller.snapshot()
            assert len(rows) == 2 and all(row['status'] == 'LIVE' for row in rows), rows
            assert {row['handle'] for row in rows} == {fresh(source_token, 'NORMAL').blui_native_handle,
                                                     fresh(state['second'], 'NORMAL').blui_native_handle}
            assert len(shell_hover._controller._registrations) == 2
            for row in rows:
                assert 0 <= row['rect'][0] < row['rect'][2] <= preview.width
                assert 0 <= row['rect'][1] < row['rect'][3] <= preview.height
            print('PASS OWN live DWM registration and separate no-activate preview; GL screenshot is not DWM pixel evidence', flush=True)
            shell_hover.close()
            assert not shell_hover._controller._registrations
            state['point'] = None
            execute(fresh(state['bar'], 'TASKBAR'), 'blui_start_menu', invoke=True)
            starts = taskbar_windows.role_windows('STARTMENU')
            assert len(starts) == 1
            state['start'], state['focus_hold'] = token(starts[0]), True
            print('QA_FOREGROUND_READ_ONLY: keep exact OWN Start token foreground during wheel/search; restore real read before child-context lifetime check', flush=True)
            settings = bpy.context.window_manager.blui_start_menu_settings
            settings.query, settings.section = '', 'ALL'
            contents.sync(settings, start_menu.snapshot())
            state['drawn'].clear()
            taskbar_windows.redraw()
            next_phase(6, .4)
        elif phase == 6:
            menus = taskbar_windows.role_windows('STARTMENU')
            assert len(menus) == 1
            start = fresh(state['start'], 'STARTMENU')
            settings = bpy.context.window_manager.blui_start_menu_settings
            assert len(settings.items) == 80
            state['before_drawn'] = set(state['drawn'])
            assert state['before_drawn'] and len(state['before_drawn']) < 80, 'UIList must draw the visible subset'
            state['ui_scale'] = (bpy.context.preferences.view.ui_scale, bpy.context.preferences.system.ui_scale)
            state['extent'] = extent(start)
            state['drawn'].clear()
            point = (min(start.width // 3, round(150 * state['ui_scale'][1])), start.height // 2)
            move(start, point)
            for _ in range(8):
                start.event_simulate(type='WHEELDOWNMOUSE', value='PRESS', x=point[0], y=point[1])
            next_phase(7, .4)
        elif phase == 7:
            start = fresh(state['start'], 'STARTMENU')
            assert (bpy.context.preferences.view.ui_scale, bpy.context.preferences.system.ui_scale) == state['ui_scale']
            assert all(abs(current - previous) < .001 for current, previous in zip(extent(start), state['extent'])), 'Wheel changed View2D zoom'
            assert state['drawn'] - state['before_drawn'], ('Wheel did not scroll Programs UIList', state['drawn'], state['before_drawn'])
            from qa_shell_pixels import verify
            verify(start, 'start-menu')
            settings = bpy.context.window_manager.blui_start_menu_settings
            settings.query = 'QA Item 071'
            contents.sync(settings, start_menu.snapshot())
            assert len(settings.items) == 1 and settings.items[0].app_id == state['fake_rows'][71]['id']
            step = max(10, round(20 * state['ui_scale'][1]))
            x = min(start.width // 3, round(110 * state['ui_scale'][1]))
            state['probes'] = [(x, y) for y in range(start.height - step, step, -step)]
            next_phase(8, .3)
        elif phase == 8:
            start = fresh(state['start'], 'STARTMENU')
            hovered, identity = override_hovered(start)
            if hovered == 'WM_OT_blui_start_launch' and identity == state['fake_rows'][71]['id']:
                right_click(start, state['probe'])
                next_phase(9)
            else:
                assert state['probes'], 'Could not find the displayed app button via live native hover context'
                state['probe'] = state['probes'].pop(0)
                move(start, state['probe'])
                state['due'] = time.monotonic() + .05
        else:
            popup = menu('START_APP')
            assert taskbar_windows.menu_state(popup)['app_id'] == state['fake_rows'][71]['id']
            from blui_desktop import start_menu_ui
            assert tuple(taskbar_windows.menu_state(popup)['source']) == state['start']
            state['focus_hold'] = False
            start_menu_ui._focus_tick()  # Real foreground + real owned-child predicate.
            fresh(state['start'], 'STARTMENU')
            execute(popup, 'blui_shell_popup_close')
            for window in list(taskbar_windows.role_windows('STARTMENU')):
                execute(window, 'blui_shell_popup_close')
            assert {workspace.name for workspace in bpy.data.workspaces} == workspaces
            assert fresh(source_token, 'NORMAL').screen.as_pointer() == source_screen
            assert len([window for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL']) == 2
            print('check_shell_redesign_ui: PASS (native app/Start/app-row contexts outside bar, OWN live DWM preview, real UIList wheel without DPI/zoom change, parent lifetime; zero external app launches/system changes)', flush=True)
            finish(0)
        return .05
    except Exception:
        traceback.print_exc()
        print('check_shell_redesign_ui: FAIL', flush=True)
        finish(1)


bpy.app.timers.register(tick, first_interval=.6)
