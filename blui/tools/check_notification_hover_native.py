# SPDX-License-Identifier: GPL-2.0-or-later
"""ROOT ONLY serial private-source hover callbacks + independent passive tip QA.

--factory-startup --enable-event-simulate with isolated CONFIG. No Explorer,
system taskbar/AppBar, external app callbacks, broadcasts or system cursor move.
Synthetic pointer events use real native button hit-test; callback pipe/Win32
delivery are real. Only the private fixture-owned helper receives NIM packets.
"""
import ctypes as c
from ctypes import wintypes as w
import os
import struct
import sys
import tempfile
import time
import traceback
import uuid
import bpy
from blui_desktop import monitors, native_windows, notification_client as notify, notification_host
from blui_desktop import notification_hover, runtime, session, taskbar_windows, window_placement

temporary = tempfile.TemporaryDirectory(prefix='blui_notification_hover_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
os.environ['BLUI_NOTIFY_QA_PRIVATE'] = '1'
session.disable_for_tests = True
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
notification_hover.close()
notify.close()
bpy.context.preferences.view.ui_scale = 1
source = next(window for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL')
source_key = (source.as_pointer(), source.blui_native_handle)
source_handle = int(source.blui_native_handle)
user = notification_host._api()
for name, result, args in (
    ('SetWindowLongPtrW', c.c_ssize_t, [w.HWND, c.c_int, c.c_ssize_t]),
    ('CallWindowProcW', c.c_ssize_t, [c.c_void_p, w.HWND, w.UINT, w.WPARAM, w.LPARAM]),
    ('LoadIconW', w.HICON, [w.HINSTANCE, c.c_void_p]),
    ('GetForegroundWindow', w.HWND, []),
):
    function = getattr(user, name)
    function.argtypes, function.restype = args, result
source_identity = native_windows._identity(user, source_handle)
assert source_identity and source_identity[0] == os.getpid()
callback_message = user.RegisterWindowMessageW('BLUI_QA.Hover.' + str(os.getpid()) + '.' + uuid.uuid4().hex)
callback_type = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
old_procedure = int(user.GetWindowLongPtrW(source_handle, -4))
callbacks = []


@callback_type
def receive(handle, message, wparam, lparam):
    if int(handle) == source_handle and message == callback_message:
        callbacks.append((int(wparam), int(lparam)))
        return 0
    return user.CallWindowProcW(c.c_void_p(old_procedure), handle, message, wparam, lparam)


procedure = c.cast(receive, c.c_void_p).value
assert int(user.SetWindowLongPtrW(source_handle, -4, procedure)) == old_procedure
state = {'phase': 0, 'due': 0., 'started': time.monotonic(), 'bar': None,
         'owner': None, 'target': None, 'tip': None, 'uid': 151}


def own_bar():
    key = state['bar']
    window = next((window for window in taskbar_windows.role_windows('TASKBAR')
                   if (window.as_pointer(), window.blui_native_handle) == key), None)
    assert window is not None
    assert window_placement._own(user, int(window.blui_native_handle))[0] == os.getpid()
    return window


def packet(message):
    assert native_windows._identity(user, source_handle) == source_identity
    identity = native_windows._identity(user, state['target'])
    assert identity == state['target_identity'] and identity[0] == state['owner'].helper_pid
    assert identity[3] == 'BLUI_QA_NotificationHost'
    icon = user.LoadIconW(None, c.c_void_p(32512))
    assert 0 < source_handle <= 0xffffffff and 0 < icon <= 0xffffffff
    data = bytearray(964)
    struct.pack_into('<8I', data, 0, 0, message, 956, source_handle, state['uid'], 7, callback_message, icon)
    text = 'BLUI 真实悬停提示\nPrivate OWN hover notification\0'.encode('utf-16-le')
    data[32:32 + len(text)] = text
    struct.pack_into('<I', data, 808, 4)
    buffer = c.create_string_buffer(bytes(data))
    value = notification_host._CopyData(1, len(data), c.cast(buffer, c.c_void_p))
    result = c.c_size_t()
    assert user.SendMessageTimeoutW(state['target'], 0x4a, source_handle, c.addressof(value),
                                    0x3, 1000, c.byref(result)) and result.value == 1


def hovered(window):
    area = window.screen.areas[0]
    region = next(region for region in area.regions if region.type == 'WINDOW')
    with bpy.context.temp_override(window=window, area=area, region=region):
        button = getattr(bpy.context, 'blui_shell_hover_button', None)
        return button.key if button and button.bl_rna.identifier == 'WM_OT_blui_notification_action' else None


def provider():
    if state.get('outside'):
        return (-10000, -10000)
    bar = own_bar()
    rect = window_placement.bounds(bar.blui_native_handle)['rect']
    x, y = state['point']
    return rect[0] + x, rect[1] + bar.height - y


def finish(code):
    try:
        notification_hover.close()
        notify.close()
        if native_windows._identity(user, source_handle) == source_identity:
            current = int(user.GetWindowLongPtrW(source_handle, -4))
            assert current in (procedure, old_procedure), 'Never replace another WNDPROC'
            if current == procedure:
                user.SetWindowLongPtrW(source_handle, -4, old_procedure)
        for window in list(taskbar_windows.role_windows()):
            taskbar_windows.close_window(window)
    except Exception:
        traceback.print_exc()
        code = 1
    temporary.cleanup()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def tick():
    try:
        assert time.monotonic() - state['started'] < 45, ('Hover QA timed out', state['phase'], callbacks)
        notify.poll()
        if time.monotonic() < state['due']:
            return .05
        phase = state['phase']
        if phase == 0:
            assert notify.start()
            state['owner'] = notify._owner
            runtime._monitors = monitors.snapshot()
            state['phase'] = 1
        elif phase == 1:
            value = notify.snapshot()
            assert not value['error'], value['error']
            if not value['enabled']:
                return .05
            state['target'] = int(value['host_handle'])
            state['target_identity'] = native_windows._identity(user, state['target'])
            packet(0)
            packet(4)
            state['phase'] = 2
        elif phase == 2:
            icons = notify.snapshot()['icons']
            if len(icons) != 1 or icons[0]['version'] != 4 or not notify.icon_value(icons[0]):
                return .05
            state['key'] = icons[0]['key']
            scale = bpy.context.preferences.system.ui_scale
            bar = taskbar_windows.create(bpy.context, 'TASKBAR', round(960 * scale), round(56 * scale))
            state['bar'] = (bar.as_pointer(), bar.blui_native_handle)
            display = next(row for row in runtime._monitors['monitors'] if row['primary'])
            taskbar_windows._bindings[taskbar_windows._identity(bar)] = display['device']
            rect = [display['work'][0] + 20, display['work'][3] - bar.height - 20,
                    display['work'][0] + 20 + bar.width, display['work'][3] - 20]
            window_placement.place(bar.blui_native_handle, rect, runtime._monitors, preferred=display['device'])
            state['scan'] = [(x, round(bar.height * fraction)) for x in range(
                max(4, bar.width - round(420 * scale)), bar.width - 4, max(4, round(6 * scale)))
                for fraction in (.25, .5, .75)]
            state['point'] = state['scan'].pop(0)
            bar.event_simulate(type='MOUSEMOVE', value='NOTHING', x=state['point'][0], y=state['point'][1])
            state['phase'], state['due'] = 3, time.monotonic() + .2
        elif phase == 3:
            bar = own_bar()
            if hovered(bar) == state['key']:
                notification_hover.tick(provider)
                state['phase'], state['due'] = 4, time.monotonic() + .4
            else:
                assert state['scan'], 'No native notification hover button found'
                state['point'] = state['scan'].pop(0)
                bar.event_simulate(type='MOUSEMOVE', value='NOTHING', x=state['point'][0], y=state['point'][1])
                state['due'] = time.monotonic() + .06
        elif phase == 4:
            notification_hover.tick(provider)
            assert not notification_hover.error(), notification_hover.error()
            tips = [window for window in taskbar_windows.role_windows('TASK_CHOOSER')
                    if taskbar_windows.menu_state(window).get('kind') == 'NOTIFICATION_TIP']
            assert len(tips) == 1
            tip, bar = tips[0], own_bar()
            handle = int(tip.blui_native_handle)
            assert window_placement._own(user, handle)[0] == os.getpid()
            assert user.GetWindowLongPtrW(handle, -20) & 0x08000000
            assert user.GetForegroundWindow() != handle, 'Tooltip must not steal foreground focus'
            assert tip.screen.as_pointer() != bar.screen.as_pointer()
            tip_rect = window_placement.bounds(tip.blui_native_handle)['rect']
            bar_rect = window_placement.bounds(bar.blui_native_handle)['rect']
            assert tip_rect[3] <= bar_rect[1] and tip.height > 40, 'Tip is clipped into the thin bar'
            state['tip'] = (tip.as_pointer(), tip.blui_native_handle)
            state['phase'], state['due'] = 5, time.monotonic() + .4
        elif phase == 5:
            notification_hover.tick(provider)
            if len(callbacks) < 2:
                return .05
            assert [item[1] & 0xffff for item in callbacks] == [0x2a1, 0x406], callbacks
            assert all(item[1] >> 16 == state['uid'] for item in callbacks)
            tip = next(window for window in taskbar_windows.role_windows('TASK_CHOOSER')
                       if (window.as_pointer(), window.blui_native_handle) == state['tip'])
            with bpy.context.temp_override(window=tip):
                assert bpy.ops.screen.screenshot(filepath='D:/BlenderUI/build/notification-hover-own-tip.png') == {'FINISHED'}
            print('PASS real private HOVER_ENTER/NIN_POPUPOPEN once + independent NOACTIVATE rendered tip', flush=True)
            state['outside'] = True
            notification_hover.tick(provider)
            notification_hover.close()
            notification_hover.close()
            state['phase'], state['due'] = 6, time.monotonic() + .4
        elif phase == 6:
            if len(callbacks) < 4:
                return .05
            assert [item[1] & 0xffff for item in callbacks] == [0x2a1, 0x406, 0x2a3, 0x407], callbacks
            assert not taskbar_windows.role_windows('TASK_CHOOSER')
            packet(2)
            notify.close()
            state['phase'] = 7
        elif phase == 7:
            if not state['owner'].finished.is_set():
                return .05
            assert native_windows._identity(user, state['target']) != state['target_identity']
            assert any((window.as_pointer(), window.blui_native_handle) == source_key
                       for window in bpy.context.window_manager.windows)
            print('check_notification_hover_native: PASS (private real hover callbacks/once leave, passive external tip, owned cleanup)', flush=True)
            finish(0)
        return .05
    except Exception:
        traceback.print_exc()
        finish(1)


bpy.app.timers.register(tick, first_interval=.5)
