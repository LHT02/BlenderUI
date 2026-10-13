# SPDX-License-Identifier: GPL-2.0-or-later
"""Serial, owned-PID native taskbar QA. Run by the primary agent only.

BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python ...
Never hides Windows taskbars, launches applications, manipulates other processes,
or edits user CONFIG. The fixture may close/minimize only this disposable QA PID.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest import mock
import bpy
from blui_desktop import icon_cache, native_windows, runtime, session, taskbar_actions, taskbar_windows, window_placement

temporary = tempfile.TemporaryDirectory(prefix='blui_taskbar_ui_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
session.disable_for_tests = True
source = bpy.context.window
source_pointer = source.as_pointer()
original_workspaces = {workspace.name for workspace in bpy.data.workspaces}
started = time.monotonic()
state = {'phase': 0, 'due': 0, 'bar': None, 'second': None, 'group': None}
user = native_windows._api()


def own_row(window, *, active=False):
    handle = int(window.blui_native_handle)
    identity = native_windows._identity(user, handle)
    assert identity and identity[0] == os.getpid(), 'fixture may act only on its own PID'
    pid, thread, created, name = identity
    return {'handle': str(handle), 'pid': pid, 'thread_id': thread, 'process_started': created,
            'window_class': name, 'title': 'QA owned ' + str(window.as_pointer()),
            'actionable': True, 'active': active, 'minimized': bool(user.IsIconic(handle)),
            **native_windows._metadata(pid), 'monitor': taskbar_windows.device(state['bar'])}


def execute(window, name, **properties):
    with bpy.context.temp_override(window=window):
        value = getattr(bpy.ops.wm, name)(**properties)
    assert value == {'FINISHED'}, (name, value)


def new_component(window):
    before = {item.as_pointer() for item in bpy.context.window_manager.windows}
    execute(window, 'window_new', workspace='Files')
    added = [item for item in bpy.context.window_manager.windows if item.as_pointer() not in before]
    assert len(added) == 1
    return added[0]


def finish(code):
    # Exit this disposable process, not Blender's shared quit.blend save path.
    temporary.cleanup()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def tick():
    try:
        if time.monotonic() - started > 45:
            raise AssertionError('Native taskbar QA timed out')
        if time.monotonic() < state['due']:
            return .05
        phase = state['phase']
        if phase == 0:
            runtime._monitors = {'coordinate_space': 'physical', 'monitors': []}
            execute(source, 'blui_taskbar_open', all_displays=False)
            assert taskbar_windows.needs_service() and taskbar_windows._pending
            assert not taskbar_windows.role_windows('TASKBAR')
            state['phase'] = 1
        elif phase == 1:
            bars = taskbar_windows.role_windows('TASKBAR')
            if not bars:
                return .05
            assert len(bars) == 1
            bar = state['bar'] = bars[0]
            assert bar.blui_is_taskbar and bar.blui_shell_role == 'TASKBAR'
            assert bar.screen.as_pointer() != source.screen.as_pointer()
            assert bar.screen.areas[0].type == 'INFO'
            assert any(region.type == 'WINDOW' for region in bar.screen.areas[0].regions)
            handle = int(bar.blui_native_handle)
            style, extended = user.GetWindowLongPtrW(handle, -16), user.GetWindowLongPtrW(handle, -20)
            assert not style & 0x00C00000, 'standalone taskbar must not have a caption'
            assert extended & 0x08000000, 'taskbar must be NOACTIVATE'
            assert extended & 0x80, 'shell UI must not be an application task'
            assert 24 <= bar.height <= 150 and bar.width >= 500
            assert {workspace.name for workspace in bpy.data.workspaces} == original_workspaces
            execute(source, 'blui_taskbar_open', all_displays=False)
            assert taskbar_windows.role_windows('TASKBAR') == [bar]
            state['second'] = new_component(bar)
            assert state['second'].blui_shell_role == 'NORMAL'
            assert state['second'].height > 200, 'Files opened from a thin bar must not inherit its height'
            runtime._tasks = [own_row(source), own_row(state['second'])]
            runtime._last_tasks = time.monotonic() + 3600
            group = taskbar_actions.current_groups(bar)
            assert len(group) == 1 and len(group[0]['tasks']) == 2, 'one executable must have one task icon'
            state['group'] = group[0]['key']
            icon_cache.value(group[0]['executable'])
            execute(bar, 'blui_taskbar_layout', mode='LEFT')
            assert taskbar_windows.alignment() == 'LEFT'
            execute(bar, 'blui_taskbar_layout', mode='CENTER')
            assert taskbar_windows.alignment() == 'CENTER'
            state['hidden_mock'] = mock.patch.object(taskbar_windows.taskbar, 'snapshot',
                                                     return_value={'enabled': True, 'hidden_count': 1})
            state['hidden_mock'].start()
            taskbar_windows.tick(runtime.monitor_snapshot())
            state['phase'], state['due'] = 2, time.monotonic() + .5
        elif phase == 2:
            bar = state['bar']
            if state.get('hidden_mock'):
                display = next(row for row in runtime.monitor_snapshot()['monitors']
                               if row['device'] == taskbar_windows.device(bar))
                assert window_placement.bounds(bar.blui_native_handle)['rect'][3] == display['rect'][3]
                state.pop('hidden_mock').stop()
                taskbar_windows.tick(runtime.monitor_snapshot())
                print('PASS Only the QA bar follows simulated hidden-system-bar state to physical edge; real system bar unchanged', flush=True)
            rows = taskbar_actions.current_groups(bar)
            if not icon_cache.value(rows[0]['executable']):
                return .05
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from qa_shell_pixels import verify
            verify(bar, 'taskbar')
            execute(bar, 'blui_taskbar_group', key=state['group'])
            menus = taskbar_windows.role_windows('TASK_CHOOSER')
            assert len(menus) == 1 and menus[0].height >= 160
            assert menus[0].screen.as_pointer() not in (bar.screen.as_pointer(), source.screen.as_pointer())
            execute(menus[0], 'blui_shell_popup_close')
            assert not taskbar_windows.role_windows('TASK_CHOOSER')
            runtime._tasks = [own_row(state['second'], active=True)]
            if user.SetForegroundWindow(int(state['second'].blui_native_handle)):
                execute(bar, 'blui_taskbar_group', key=state['group'])
            else:
                # Automated background processes may lack foreground permission.
                # Simulate ONLY this read for the already verified owned target;
                # the actual minimize/restore Win32 writes remain real and PID-checked.
                print('QA_FOREGROUND_LOCK: simulate owned foreground read for toggle branch', flush=True)
                with (mock.patch.object(native_windows, '_api', return_value=user),
                      mock.patch.object(user, 'GetForegroundWindow', return_value=int(state['second'].blui_native_handle))):
                    execute(bar, 'blui_taskbar_group', key=state['group'])
            state['phase'], state['due'] = 3, time.monotonic() + .4
        elif phase == 3:
            assert user.IsIconic(int(state['second'].blui_native_handle)), 'active single-window click must minimize'
            runtime._tasks = [own_row(state['second'])]
            try:
                execute(state['bar'], 'blui_taskbar_group', key=state['group'])
            except RuntimeError as error:
                assert 'Windows did not allow foreground activation' in str(error)
                print('PASS Foreground refusal is reported; owned restore still proceeds', flush=True)
            state['phase'], state['due'] = 4, time.monotonic() + .4
        elif phase == 4:
            assert not user.IsIconic(int(state['second'].blui_native_handle)), 'single-window click must restore'
            execute(state['bar'], 'blui_taskbar_settings')
            menu = taskbar_windows.role_windows('TASK_CHOOSER')[0]
            state['menu_pointer'] = menu.as_pointer()
            menu.event_simulate(type='ESC', value='PRESS')
            state['phase'], state['due'] = 5, time.monotonic() + .4
        elif phase == 5:
            assert not taskbar_windows.role_windows('TASK_CHOOSER'), 'native INFO popup ESC must close chooser'
            for window in list(bpy.context.window_manager.windows):
                if window.blui_shell_role == 'NORMAL':
                    execute(window, 'window_close', force_close=True)
            assert bpy.context.window_manager.windows[:] == [state['bar']]
            normal = new_component(state['bar'])
            assert normal.blui_shell_role == 'NORMAL' and normal.height > 200
            assert normal.screen.as_pointer() != state['bar'].screen.as_pointer()
            assert normal.screen.areas[0].type == 'FILE_BROWSER'
            print('check_taskbar_ui: PASS (pending, independent INFO/styles, grouping/icons, layouts, own min/restore, ESC, Files sizing)')
            finish(0)
        return .05
    except Exception:
        traceback.print_exc()
        print('check_taskbar_ui: FAIL')
        finish(1)


bpy.app.timers.register(tick, first_interval=.6)
