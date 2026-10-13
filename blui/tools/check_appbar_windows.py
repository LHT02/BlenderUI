# SPDX-License-Identifier: GPL-2.0-or-later
"""Serial, disposable owned-PID native AppBar QA. PRIMARY AGENT RUNS ONLY.

Use an isolated BLENDER_USER_CONFIG, --factory-startup --enable-event-simulate
--python-exit-code 1 --python this file. It temporarily reserves primary-monitor
space using its own new AppBar and must restore it on success/failure/timeout.
No system taskbar hide/restore, Explorer restart, foreign-window activation,
launch, movement or resize is performed. Only this process exits at completion.
"""
import ctypes as c
from ctypes import wintypes as w
import os
import sys
import tempfile
import time
import traceback
import bpy
from blui_desktop import monitors, native_windows, runtime, session, taskbar_appbar, taskbar_windows, window_placement


session.disable_for_tests = True
temporary = tempfile.TemporaryDirectory(prefix='blui_appbar_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
# Keep the fixture's registration isolated from automatic role-window geometry
# and restore services. This only changes timers in this disposable QA process.
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)

controller = taskbar_appbar.AppBarController()
user = window_placement._api()
user.IsZoomed.argtypes, user.IsZoomed.restype = [w.HWND], w.BOOL
user.GetClientRect.argtypes, user.GetClientRect.restype = [w.HWND, c.POINTER(w.RECT)], w.BOOL
user.ClientToScreen.argtypes, user.ClientToScreen.restype = [w.HWND, c.POINTER(w.POINT)], w.BOOL
user.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user.SendMessageW.restype = w.LPARAM

started = time.monotonic()
initial = monitors.snapshot()
assert initial['monitors'], 'No connected display for native AppBar QA'
display = next((row for row in initial['monitors'] if row['primary']), initial['monitors'][0])
device = display['device']
baseline = {row['device']: row['work'][:] for row in initial['monitors']}
source = next(window for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL')
state = {'phase': 0, 'due': 0.0, 'source': (source.as_pointer(), source.blui_native_handle),
         'bar': None, 'rect': None, 'cleanup_done': False}


def live(key, role):
    value = next((window for window in bpy.context.window_manager.windows
                  if (window.as_pointer(), window.blui_native_handle) == key), None)
    assert value is not None and value.blui_shell_role == role, 'Fixture-owned window disappeared/changed'
    handle = window_placement._handle(value.blui_native_handle)
    identity = window_placement._own(user, handle)
    assert identity[0] == os.getpid(), 'QA never acts on another process'
    return value, handle, identity


def recheck(handle, identity):
    assert window_placement._own(user, handle) == identity, 'Owned HWND identity changed before action'


def move_own(key, role, rect, *, topmost=False):
    _window, handle, identity = live(key, role)
    physical = display['rect']
    assert (physical[0] <= rect[0] < rect[2] <= physical[2] and
            physical[1] <= rect[1] < rect[3] <= physical[3]), 'QA placement must remain on its monitor'
    recheck(handle, identity)
    # ASYNC | NOACTIVATE | NOOWNERZORDER, and NOZORDER for the normal source.
    flags = 0x4000 | 0x10 | 0x200 | (0 if topmost else 0x4)
    assert user.SetWindowPos(handle, -1 if topmost else None, rect[0], rect[1],
                             rect[2] - rect[0], rect[3] - rect[1], flags), 'Owned SetWindowPos failed'


def show_source(command):
    _window, handle, identity = live(state['source'], 'NORMAL')
    recheck(handle, identity)
    assert command in (3, 9), 'Only owned maximize/restore is allowed'
    assert user.ShowWindowAsync(handle, command), 'Owned maximize/restore failed'


def current_display():
    snapshot = monitors.snapshot()
    current = next((row for row in snapshot['monitors'] if row['device'] == device), None)
    assert current is not None and current['rect'] == display['rect'], 'Monitor topology changed during QA'
    return snapshot, current


def client_bottom():
    _window, handle, identity = live(state['source'], 'NORMAL')
    rect = w.RECT()
    assert user.GetClientRect(handle, c.byref(rect)), 'Cannot read owned client area'
    point = w.POINT(0, rect.bottom)
    assert user.ClientToScreen(handle, c.byref(point)), 'Cannot map owned client coordinates'
    recheck(handle, identity)
    return point.y


def native_callback(notification, value):
    _window, handle, identity = live(state['bar'], 'TASKBAR')
    recheck(handle, identity)
    user.SendMessageW(handle, taskbar_appbar.CALLBACK_MESSAGE, notification, value)


def close_bar():
    key, state['bar'] = state.get('bar'), None
    if key is None:
        return
    window = next((item for item in bpy.context.window_manager.windows
                   if (item.as_pointer(), item.blui_native_handle) == key), None)
    if window is None:
        return
    assert window.blui_shell_role == 'TASKBAR'
    handle = window_placement._handle(window.blui_native_handle)
    identity = window_placement._own(user, handle)
    assert identity[0] == os.getpid()
    recheck(handle, identity)
    with bpy.context.temp_override(window=window):
        assert bpy.ops.wm.window_close(force_close=True) == {'FINISHED'}


def cleanup():
    # AppBar removal comes before native HWND destruction, even on assertions.
    controller.close()
    close_bar()
    state['cleanup_done'] = True


def work_restored():
    snapshot, _current = current_display()
    return all(row['work'] == baseline[row['device']] for row in snapshot['monitors']
               if row['device'] in baseline)


def finish(code):
    try:
        if not state['cleanup_done']:
            cleanup()
        if not work_restored():
            print('QA_CLEANUP_WARNING: work area has not returned to its pre-QA snapshot', flush=True)
            code = 1
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        temporary.cleanup()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)


def tick():
    try:
        if time.monotonic() - started > 45:
            raise TimeoutError('Native AppBar QA exceeded 45 seconds')
        if time.monotonic() < state['due']:
            return .05
        phase = state['phase']
        if phase == 0:
            before = {window.as_pointer() for window in bpy.context.window_manager.windows}
            source, _handle, _identity = live(state['source'], 'NORMAL')
            width, height = display['rect'][2] - display['rect'][0], round(56 * display['dpi'][1] / 96)
            with bpy.context.temp_override(window=source):
                assert bpy.ops.wm.blui_shell_window_create(role='TASKBAR', width=width, height=height) == {'FINISHED'}
            added = [window for window in bpy.context.window_manager.windows if window.as_pointer() not in before]
            assert len(added) == 1 and added[0].blui_shell_role == 'TASKBAR'
            state['bar'] = (added[0].as_pointer(), added[0].blui_native_handle)
            bar, _handle, _identity = live(state['bar'], 'TASKBAR')
            state['rect'] = controller.reconcile({device: bar}, initial, 56)[device]
            move_own(state['bar'], 'TASKBAR', state['rect'], topmost=True)
            work = baseline[device]
            normal_width, normal_height = min(800, work[2] - work[0]), min(600, work[3] - work[1] - height)
            normal_rect = [work[0], work[1], work[0] + normal_width, work[1] + normal_height]
            move_own(state['source'], 'NORMAL', normal_rect)
            state['phase'], state['due'] = 1, time.monotonic() + .35
        elif phase == 1:
            _snapshot, current = current_display()
            if current['work'][3] != state['rect'][1]:
                return .05
            assert state['rect'][3] - state['rect'][1] == round(56 * display['dpi'][1] / 96)
            assert current['work'][:3] == baseline[device][:3], 'Only the primary bottom edge may be reserved'
            print('PASS Own AppBar reserves bottom work area at 56 logical pixels', flush=True)
            show_source(3)
            state['phase'], state['due'] = 2, time.monotonic() + .35
        elif phase == 2:
            _source, handle, _identity = live(state['source'], 'NORMAL')
            if not user.IsZoomed(handle) or client_bottom() > state['rect'][1] + 1:
                return .05
            frame = window_placement.bounds(str(handle))['frame']
            assert frame[3] <= state['rect'][1] + 2, ('Owned maximized visible frame overlaps AppBar', frame, state['rect'])
            print('PASS Own maximized normal window avoids reserved taskbar', flush=True)
            show_source(9)
            bar, _handle, _identity = live(state['bar'], 'TASKBAR')
            snapshot, _current = current_display()
            state['rect'] = controller.reconcile({device: bar}, snapshot, 80)[device]
            move_own(state['bar'], 'TASKBAR', state['rect'], topmost=True)
            state['phase'], state['due'] = 3, time.monotonic() + .35
        elif phase == 3:
            _snapshot, current = current_display()
            if current['work'][3] != state['rect'][1]:
                return .05
            assert state['rect'][3] - state['rect'][1] == round(80 * display['dpi'][1] / 96)
            show_source(3)
            state['phase'], state['due'] = 4, time.monotonic() + .35
        elif phase == 4:
            _source, handle, _identity = live(state['source'], 'NORMAL')
            if not user.IsZoomed(handle) or client_bottom() > state['rect'][1] + 1:
                return .05
            print('PASS 80 logical pixels updates reservation and own maximized client avoids it', flush=True)
            bar, bar_handle, _identity = live(state['bar'], 'TASKBAR')
            generation = taskbar_appbar.notification_state(bar)['generation']
            native_callback(1, 0)  # ABN_POSCHANGED, sent only to this fixture HWND.
            assert taskbar_appbar.notification_state(bar)['generation'] != generation
            snapshot, _current = current_display()
            controller.reconcile({device: bar}, snapshot, 80)
            native_callback(2, 1)  # ABN_FULLSCREENAPP begin.
            assert taskbar_appbar.is_fullscreen(bar)
            assert not user.GetWindowLongPtrW(bar_handle, -20) & 0x8, 'Own bar must leave TOPMOST during fullscreen'
            taskbar_windows._topmost(bar)
            assert not user.GetWindowLongPtrW(bar_handle, -20) & 0x8, 'Geometry helpers must not override fullscreen'
            taskbar_windows._screen_bar_place(bar, state['rect'])
            assert not user.GetWindowLongPtrW(bar_handle, -20) & 0x8, 'Physical placement must preserve fullscreen z-order'
            native_callback(2, 0)
            assert not taskbar_appbar.is_fullscreen(bar)
            assert user.GetWindowLongPtrW(bar_handle, -20) & 0x8, 'Own bar must restore TOPMOST after fullscreen'
            print('PASS Native own-only generation/fullscreen notifications and topmost guard', flush=True)
            show_source(9)
            cleanup()
            state['phase'], state['due'] = 5, time.monotonic() + .35
        elif phase == 5:
            if not work_restored():
                return .05
            assert controller.snapshot() == {}
            print('check_appbar_windows: PASS (owned native AppBar, work-area reservation/restore, 56->80 height, maximize avoidance, fullscreen notifications)', flush=True)
            finish(0)
        return .05
    except Exception:
        traceback.print_exc()
        # This finally path unregisters before closing its destination; no
        # foreign window/process is ever a cleanup target.
        finish(1)


bpy.app.timers.register(tick, first_interval=.4)
