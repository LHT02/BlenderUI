# SPDX-License-Identifier: GPL-2.0-or-later
"""OWN-only native notification UI QA. Run serially by the primary agent.

BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python ...
Uses a private receiver, never TaskbarCreated broadcasts, Explorer, real system
taskbar hiding, AppBar registration, external applications or user CONFIG.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import traceback
import uuid
import bpy
from blui_desktop import client as jobs, native_windows, notification_client as notify
from blui_desktop import notification_host, notification_ui, runtime, session, taskbar_windows, window_placement

temporary = tempfile.TemporaryDirectory(prefix='blui_notification_ui_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
os.environ['BLUI_NOTIFY_QA_PRIVATE'] = '1'
session.disable_for_tests = True
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
notify.close()
source = bpy.context.window
assert source.blui_shell_role == 'NORMAL'
source_handle = int(source.blui_native_handle)
source_pointer, source_screen = source.as_pointer(), source.screen.as_pointer()
original_workspaces = {workspace.name for workspace in bpy.data.workspaces}
bpy.context.preferences.view.ui_scale = 1
user = notification_host._api()
source_identity = native_windows._identity(user, source_handle)
assert source_identity and source_identity[0] == os.getpid()
user.SetWindowLongPtrW.argtypes, user.SetWindowLongPtrW.restype = [w.HWND, c.c_int, c.c_ssize_t], c.c_ssize_t
user.CallWindowProcW.argtypes, user.CallWindowProcW.restype = [c.c_void_p, w.HWND, w.UINT, w.WPARAM, w.LPARAM], c.c_ssize_t
user.LoadIconW.argtypes, user.LoadIconW.restype = [w.HINSTANCE, c.c_void_p], w.HICON
callback_message = user.RegisterWindowMessageW('BLUI_QA.Notification.' + str(os.getpid()) + '.' + uuid.uuid4().hex)
assert 0xc000 <= callback_message <= 0xffff
callback_type = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
old_procedure = int(user.GetWindowLongPtrW(source_handle, -4))
assert old_procedure
callbacks = []
operator_calls, command_calls = [], []
action_type = notification_ui.WM_OT_blui_notification_action
original_invoke, original_execute = action_type.invoke, action_type.execute
original_poll = action_type.__dict__['poll']
original_command = notify.command


def traced_invoke(self, context, event):
    value = ('invoke', self.key, context.window.blui_shell_role, event.type, event.value,
             event.mouse_x, event.mouse_y)
    operator_calls.append(value)
    print('NOTIFY_NATIVE_OPERATOR', value, flush=True)
    return original_invoke(self, context, event)


def traced_execute(self, context):
    value = ('execute', self.key, context.window.blui_shell_role)
    operator_calls.append(value)
    print('NOTIFY_NATIVE_OPERATOR', value, flush=True)
    return original_execute(self, context)


def traced_poll(cls, context):
    result = original_poll.__get__(None, cls)(context)
    print('NOTIFY_NATIVE_POLL', context.window.blui_shell_role if context.window else None, result, flush=True)
    return result


def traced_command(key, event, x, y):
    command_calls.append((key, event, x, y))
    print('NOTIFY_NATIVE_COMMAND', command_calls[-1], flush=True)
    return original_command(key, event, x, y)


action_type.invoke, action_type.execute, action_type.poll = traced_invoke, traced_execute, classmethod(traced_poll)
notify.command = traced_command


@callback_type
def receive(handle, message, wparam, lparam):
    if int(handle) == source_handle and message == callback_message:
        callbacks.append((int(wparam), int(lparam)))
        print('NOTIFY_NATIVE_CALLBACK', int(handle), message, int(wparam), int(lparam), flush=True)
        return 0
    return user.CallWindowProcW(c.c_void_p(old_procedure), handle, message, wparam, lparam)


procedure_pointer = c.cast(receive, c.c_void_p).value
assert native_windows._identity(user, source_handle) == source_identity
assert int(user.SetWindowLongPtrW(source_handle, -4, procedure_pointer)) == old_procedure
state = {'phase': 0, 'due': 0, 'bar': None, 'job': None, 'target': None, 'owner': None}
started = time.monotonic()


def restore_callback():
    if native_windows._identity(user, source_handle) == source_identity:
        current = int(user.GetWindowLongPtrW(source_handle, -4))
        assert current in (procedure_pointer, old_procedure), 'refuse to overwrite a replaced WNDPROC'
        if current == procedure_pointer:
            assert int(user.SetWindowLongPtrW(source_handle, -4, old_procedure)) == procedure_pointer


def finish(code):
    try:
        notify.close()
        if state['job']:
            state['job'].close()
        restore_callback()
        action_type.invoke, action_type.execute, action_type.poll = original_invoke, original_execute, original_poll
        notify.command = original_command
        for window in list(taskbar_windows.role_windows()):
            taskbar_windows.close_window(window)
        temporary.cleanup()
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)  # Only this disposable QA process.


def payload(uid, message=0, *, hidden=False):
    icon = user.LoadIconW(None, c.c_void_p(32512))  # Shared system icon, never destroyed by the fixture.
    assert 0 < source_handle <= 0xffffffff and 0 < icon <= 0xffffffff
    data = bytearray(964)
    struct.pack_into('<8I', data, 0, 0, message, 956, source_handle, uid, 15, callback_message, icon)
    tip = ('BLUI 私有通知 ' + str(uid) + '\0').encode('utf-16-le')
    data[32:32 + len(tip)] = tip
    struct.pack_into('<II', data, 288, int(hidden), 1)
    struct.pack_into('<I', data, 808, 4)
    return bytes(data)


def send(uid, message=0, *, hidden=False):
    target = state['target']
    assert native_windows._identity(user, target) == state['target_identity']
    assert state['target_identity'][0] == state['owner'].helper_pid
    assert state['target_identity'][3] == 'BLUI_QA_NotificationHost'
    assert native_windows._identity(user, source_handle) == source_identity
    data = payload(uid, message, hidden=hidden)
    buffer = c.create_string_buffer(data)
    packet = notification_host._CopyData(1, len(data), c.cast(buffer, c.c_void_p))
    result = c.c_size_t()
    assert user.SendMessageTimeoutW(target, 0x4a, source_handle, c.addressof(packet), 0x3, 1000, c.byref(result))
    assert result.value == 1


def invoke(window, name):
    area = window.screen.areas[0]
    region = next(item for item in area.regions if item.type == 'WINDOW')
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert getattr(bpy.ops.wm, name)('INVOKE_DEFAULT') == {'FINISHED'}


def move(bar, x, y):
    bar.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)


def click(bar, button):
    x, y = state['point']
    move(bar, x, y)
    print('NOTIFY_NATIVE_CLICK', button, (x, y), 'live-hover', hovered(bar),
          'source-proc', int(user.GetWindowLongPtrW(source_handle, -4)), 'expected', procedure_pointer,
          'callback-message', callback_message, flush=True)
    for value in ('PRESS', 'RELEASE'):
        bar.event_simulate(type=button, value=value, x=x, y=y)


def hovered(bar):
    area = bar.screen.areas[0]
    region = next(item for item in area.regions if item.type == 'WINDOW')
    with bpy.context.temp_override(window=bar, area=area, region=region):
        button = getattr(bpy.context, 'blui_shell_hover_button', None)
        return button.key if button and button.bl_rna.identifier == 'WM_OT_blui_notification_action' else None


def tick():
    try:
        if time.monotonic() - started > 45:
            raise AssertionError(('Private notification UI QA timed out', state['phase'], notify.snapshot(),
                                  callbacks, operator_calls, command_calls))
        notify.poll()
        if time.monotonic() < state['due']:
            return .05
        phase = state['phase']
        if phase == 0:
            assert notify.start()
            state['owner'] = notify._owner
            state['job'] = jobs.Job('monitors', timeout=8)
            state['phase'] = 1
        elif phase == 1:
            value = notify.snapshot()
            assert not value['error'], value['error']
            if not value['enabled'] or not state['job'].done():
                return .05
            runtime._monitors = state['job'].result()
            state['job'].close()
            state['job'] = None
            target = state['target'] = int(value['host_handle'])
            identity = state['target_identity'] = native_windows._identity(user, target)
            assert identity and identity[0] == state['owner'].helper_pid and identity[0] != os.getpid()
            assert identity[3] == 'BLUI_QA_NotificationHost', 'only a private owned helper may receive fixture packets'
            print('NOTIFY_NATIVE_IDENTITIES', source_identity, identity, 'registered-callback', callback_message, flush=True)
            for uid in range(101, 109):
                send(uid, hidden=uid == 108)
                send(uid, 4, hidden=uid == 108)
            state['phase'] = 2
        elif phase == 2:
            value = notify.snapshot()
            if len(value['icons']) != 8 or not all(row['version'] == 4 for row in value['icons']):
                return .05
            assert all(row['pid'] == os.getpid() and row['handle'] == str(source_handle) for row in value['icons'])
            assert all(notify.icon_value(row) > 0 for row in value['icons'])
            assert sum(row['hidden'] for row in value['icons']) == 1
            assert notification_ui.logical_width(maxicons=6) == 7 * 24
            scale = bpy.context.preferences.system.ui_scale
            bar = state['bar'] = taskbar_windows.create(bpy.context, 'TASKBAR', round(960 * scale), round(56 * scale))
            display = next((row for row in runtime._monitors['monitors'] if row['primary']), runtime._monitors['monitors'][0])
            taskbar_windows._bindings[taskbar_windows._identity(bar)] = display['device']
            work = display['work']
            rect = [work[0] + 20, work[3] - bar.height - 20, work[0] + 20 + bar.width, work[3] - 20]
            window_placement.place(bar.blui_native_handle, rect, runtime._monitors, preferred=display['device'])
            state['phase'], state['due'] = 3, time.monotonic() + .4
        elif phase == 3:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from qa_shell_pixels import verify
            verify(state['bar'], 'taskbar')
            state['scan_x'] = max(2, state['bar'].width - round(420 * bpy.context.preferences.system.ui_scale))
            state['scan_y'] = state['bar'].height // 2
            move(state['bar'], state['scan_x'], state['scan_y'])
            state['phase'], state['due'] = 4, time.monotonic() + .08
        elif phase == 4:
            bar = state['bar']
            key = hovered(bar)
            if key:
                icon = next(row for row in notify.snapshot()['icons'] if row['key'] == key)
                assert icon['pid'] == os.getpid() and not icon['hidden']
                state['key'], state['uid'] = key, icon['uid']
                assert icon['callback'] == callback_message
                state['edge_x'] = state['scan_x']
                state['scan_x'] += 2
                move(bar, state['scan_x'], state['scan_y'])
                state['phase'], state['due'] = 4.1, time.monotonic() + .08
            else:
                state['scan_x'] += max(4, round(8 * bpy.context.preferences.system.ui_scale))
                assert state['scan_x'] < bar.width - 8, 'could not find a real native notification button'
                move(bar, state['scan_x'], state['scan_y'])
                state['due'] = time.monotonic() + .08
        elif phase == 4.1:
            bar = state['bar']
            if hovered(bar) == state['key'] and state['scan_x'] < bar.width - 4:
                state['scan_x'] += 2
                move(bar, state['scan_x'], state['scan_y'])
                state['due'] = time.monotonic() + .08
            else:
                state['center_x'] = (state['edge_x'] + state['scan_x'] - 2) // 2
                state['probe_y'], state['hit_ys'] = 2, []
                move(bar, state['center_x'], state['probe_y'])
                state['phase'], state['due'] = 4.2, time.monotonic() + .08
        elif phase == 4.2:
            bar = state['bar']
            if hovered(bar) == state['key']:
                state['hit_ys'].append(state['probe_y'])
            state['probe_y'] += 2
            if state['probe_y'] < bar.height - 2:
                move(bar, state['center_x'], state['probe_y'])
                state['due'] = time.monotonic() + .08
            else:
                assert state['hit_ys'], 'no interior vertical notification hit range'
                state['point'] = state['center_x'], (min(state['hit_ys']) + max(state['hit_ys'])) // 2
                print('NOTIFY_NATIVE_BUTTON_INTERIOR', state['key'], state['edge_x'], state['scan_x'],
                      state['hit_ys'], state['point'], flush=True)
                move(bar, *state['point'])
                state['phase'], state['due'] = 4.3, time.monotonic() + .12
        elif phase == 4.3:
            assert hovered(state['bar']) == state['key']
            callbacks.clear()
            click(state['bar'], 'LEFTMOUSE')
            state['phase'], state['due'] = 5, time.monotonic() + .4
        elif phase == 5:
            if len(callbacks) < 3:
                if not state.get('left_diag'):
                    state['left_diag'] = True
                    print('NOTIFY_NATIVE_LEFT_WAIT', 'operators', operator_calls, 'commands', command_calls,
                          'queue', state['owner'].commands.qsize(), 'host', notify.snapshot()['error'],
                          'source-proc', int(user.GetWindowLongPtrW(source_handle, -4)), flush=True)
                return .05
            assert [item[1] & 0xffff for item in callbacks[-3:]] == [0x201, 0x202, 0x400]
            assert all(item[1] >> 16 == state['uid'] for item in callbacks[-3:])
            callbacks.clear()
            click(state['bar'], 'RIGHTMOUSE')
            state['phase'], state['due'] = 6, time.monotonic() + .4
        elif phase == 6:
            if len(callbacks) < 3:
                return .05
            assert [item[1] & 0xffff for item in callbacks[-3:]] == [0x204, 0x205, 0x7b]
            assert all(item[1] >> 16 == state['uid'] for item in callbacks[-3:])
            assert not taskbar_windows.role_windows('TASK_CHOOSER'), 'notification RMB must not create a clipped Blender menu'
            invoke(state['bar'], 'blui_notification_overflow')
            windows = taskbar_windows.role_windows('TASK_CHOOSER')
            assert len(windows) == 1
            menu = windows[0]
            assert menu.height > 300 and menu.screen.as_pointer() != state['bar'].screen.as_pointer()
            assert taskbar_windows.menu_state(menu)['kind'] == 'NOTIFICATION'
            assert len(bpy.context.window_manager.blui_notification_settings.items) == 8
            state['phase'], state['due'] = 7, time.monotonic() + .4
        elif phase == 7:
            from qa_shell_pixels import verify
            menu = taskbar_windows.role_windows('TASK_CHOOSER')[0]
            verify(menu, 'chooser')
            taskbar_windows.close_window(menu)
            for uid in range(101, 109):
                send(uid, 2)
            state['phase'] = 8
        elif phase == 8:
            if notify.snapshot()['icons']:
                return .05
            notify.close()
            state['phase'], state['due'] = 9, time.monotonic() + .2
        else:
            if not state['owner'].finished.is_set():
                return .05
            assert native_windows._identity(user, state['target']) != state['target_identity'], 'helper receiver must be destroyed'
            assert not notify.snapshot()['enabled'] and not notify.snapshot()['icons']
            assert source.blui_shell_role == 'NORMAL' and source.as_pointer() == source_pointer
            assert source.screen.as_pointer() == source_screen
            assert {workspace.name for workspace in bpy.data.workspaces} == original_workspaces
            restore_callback()
            assert int(user.GetWindowLongPtrW(source_handle, -4)) == old_procedure
            print('check_notification_ui_native: PASS (private OWN helper, 8 real NIM icons/cache/render, native LEFT/RIGHT callbacks, independent overflow/UIList, DELETE/async cleanup/WNDPROC restoration; no system tray changes)', flush=True)
            finish(0)
        return .05
    except Exception:
        traceback.print_exc()
        finish(1)


bpy.app.timers.register(tick, first_interval=.5)
