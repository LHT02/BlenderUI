# SPDX-License-Identifier: GPL-2.0-or-later
"""Own-process native tray callbacks, window identities and initialized screens.

Run windowed with --factory-startup --python-exit-code 1 --python this_file.py.
Never sends input/messages to another BLUI instance or closes user windows.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import sys
import time

import bpy
from blui_desktop import runtime, session
from blui_desktop import model
from bl_ui import space_filebrowser_shell

user = c.WinDLL('user32', use_last_error=True)
callback = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
user.EnumWindows.argtypes, user.EnumWindows.restype = [callback, w.LPARAM], w.BOOL
user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
user.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
user.GetWindowLongPtrW.argtypes, user.GetWindowLongPtrW.restype = [w.HWND, c.c_int], c.c_ssize_t
user.IsWindowVisible.argtypes, user.IsWindowVisible.restype = [w.HWND], w.BOOL
user.PostMessageW.argtypes, user.PostMessageW.restype = [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL
state = {'phase': 0, 'started': time.monotonic(), 'cycle': 0}
session.disable_for_tests = True


def native_windows():
    result = []

    @callback
    def visit(handle, _parameter):
        pid = w.DWORD()
        user.GetWindowThreadProcessId(handle, c.byref(pid))
        if pid.value == os.getpid():
            name, title = c.create_unicode_buffer(128), c.create_unicode_buffer(256)
            user.GetClassNameW(handle, name, len(name))
            user.GetWindowTextW(handle, title, len(title))
            if name.value in {'GHOST_WindowClass', 'BLUI_TrayWindow'}:
                result.append({'handle': int(handle), 'class': name.value, 'title': title.value,
                               'visible': bool(user.IsWindowVisible(handle)),
                               'userdata': user.GetWindowLongPtrW(handle, -21)})
        return True

    assert user.EnumWindows(visit, 0)
    return result


def inspect(label):
    windows = list(bpy.context.window_manager.windows)
    rows = native_windows()
    live = {int(window.blui_native_handle) for window in windows}
    visible = {row['handle'] for row in rows if row['class'] == 'GHOST_WindowClass' and row['visible']}
    print('TRAY_WINDOWS', label, 'native', rows, 'rna', [
        (window.blui_native_handle, window.workspace.name if window.workspace else None,
         window.screen.name if window.screen else None,
         window.screen.as_pointer() if window.screen else 0,
         [(area.type, area.width, area.height,
           [(region.type, region.width, region.height) for region in area.regions])
          for area in window.screen.areas] if window.screen else []) for window in windows], flush=True)
    if label == 'tray-second-open' and state['cycle'] == 0:
        for index, window in enumerate(windows):
            verify_drawn(window, index)
    assert visible == live, 'Visible orphan/dummy window not represented by a Blender window'
    assert len({window.screen.as_pointer() for window in windows}) == len(windows), \
        'Independent OS windows share one native screen/redraw state'
    for window in windows:
        assert window.screen and window.workspace and window.scene
        assert window.screen.areas, 'Blank native screen has no areas'
        assert any(region.type == 'WINDOW' and region.width > 0 and region.height > 0
                   for area in window.screen.areas for region in area.regions), 'Screen has no initialized content region'
    return windows


def verify_drawn(window, index):
    label = os.environ.get('BLUI_QA_TRAY_LABEL', 'after')
    assert label in {'baseline', 'after', 'release'}
    # Owned QA artifacts, outside both the source and all portable releases.
    path = Path('D:/BlenderUI/build') / ('tray-%s-window-%d.png' % (label, index))
    area = window.screen.areas[0]
    with bpy.context.temp_override(window=window, area=area):
        assert bpy.ops.screen.screenshot(filepath=str(path)) == {'FINISHED'}
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = image.size
        colors = set()
        # UI text/buttons produce more than a startup clear color, even on an empty folder.
        for y in (height - 12, height - 35, height - 62, height // 2):
            for x in range(8, width - 8, 8):
                offset = 4 * (y * width + x)
                colors.add(tuple(round(channel * 255) for channel in image.pixels[offset:offset + 3]))
        print('TRAY_DRAW_COLORS', index, len(colors), str(path), flush=True)
        assert len(colors) > 8, 'Native component window remained at its blank startup clear color'
    finally:
        bpy.data.images.remove(image)


def tray_open():
    tray = next(row for row in native_windows() if row['class'] == 'BLUI_TrayWindow')
    # NOTIFYICON_VERSION_4: LOWORD event=NIN_SELECT, HIWORD icon id=1.
    assert user.PostMessageW(tray['handle'], 0x8001, 0, (1 << 16) | 0x400)


def close_owned():
    for window in list(bpy.context.window_manager.windows):
        with bpy.context.temp_override(window=window):
            bpy.ops.wm.window_close(force_close=True)
    assert not bpy.context.window_manager.windows


def step():
    if time.monotonic() - state['started'] > 60:
        raise TimeoutError('Native tray window regression timed out')
    phase = state['phase']
    if phase == 0:
        space_filebrowser_shell.unregister()
        if bpy.app.timers.is_registered(runtime.tick):
            bpy.app.timers.unregister(runtime.tick)
        runtime.cancel_pending()
        assert len(inspect('factory-startup')) == 1
        close_owned()
        state['phase'] = 1
        return .25
    if phase == 1:
        inspect('all-closed')
        tray_open()
        state['phase'] = 2
        return .8
    if phase == 2:
        windows = inspect('tray-first-open')
        assert len(windows) == 1
        assert all(area.type == 'FILE_BROWSER' for area in windows[0].screen.areas)
        # Repeated user activation should be checked separately from no-window creation.
        state['first'] = windows[0].as_pointer()
        tray_open()
        state['phase'] = 3
        return .8
    if phase == 3:
        windows = inspect('tray-second-open')
        assert len(windows) == 2, 'A single tray callback must add exactly one independent component window'
        print('REPEATED_TRAY_WINDOW_COUNT', len(windows), flush=True)
        if state['cycle'] == 0:
            # Desktop windows share the Files workspace but use a different layout.
            # An explicit Files component request must still use its original browser.
            source = windows[-1]
            area = source.screen.areas[0]
            area.type = 'NODE_EDITOR'
            area.spaces.active.tree_type = model.TREE
            before = {window.as_pointer() for window in windows}
            with bpy.context.temp_override(window=source, area=area):
                assert bpy.ops.wm.window_new(workspace='Files') == {'FINISHED'}
            state['component'] = next(window.as_pointer() for window in bpy.context.window_manager.windows
                                      if window.as_pointer() not in before)
            state['phase'] = 4
            return .5
        return finish_cycle()
    if phase == 4:
        windows = inspect('Files-request-from-desktop-layout')
        assert len(windows) == 3
        component = next(window for window in windows if window.as_pointer() == state['component'])
        assert all(area.type == 'FILE_BROWSER' for area in component.screen.areas), \
            'Explicit Files request copied the desktop layout instead of the component layout'
        print('PASS Files component stays a file browser when opened from a desktop-derived layout', flush=True)
        return finish_cycle()


def finish_cycle():
    close_owned()
    state['cycle'] += 1
    if state['cycle'] < 6:
        state['phase'] = 1
        return .25
    print('check_tray_windows: PASS (startup, 6 close/reopen/repeated activation cycles)', flush=True)
    os._exit(0)


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.8)
