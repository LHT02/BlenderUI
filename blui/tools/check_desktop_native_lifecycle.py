# SPDX-License-Identifier: GPL-2.0-or-later
"""ROOT ONLY: owned fake-parent death, focus/layered/Node/save native regression.

--factory-startup --enable-event-simulate --python-exit-code 1 --python this file
with an isolated CONFIG. No Explorer/SPI/taskbar/host helper or foreign HWND
write. SetParent/DestroyWindow target only this fixture's owned native windows.
Only strings/instance tokens survive load/close; every RNA/native lookup is fresh.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
import bpy
from blui_desktop import model, native_windows, runtime, session
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_desktop_dpi import DesktopDpiQA
dpi_qa = DesktopDpiQA()

session.disable_for_tests = True
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
temporary = tempfile.TemporaryDirectory(prefix='blui_desktop_lifecycle_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
user = native_windows._api()
for name, result, args in (
    ('GetPropW', w.HANDLE, [w.HWND, w.LPCWSTR]),
    ('GetClassLongPtrW', c.c_ssize_t, [w.HWND, c.c_int]),
    ('SetWindowLongPtrW', c.c_ssize_t, [w.HWND, c.c_int, c.c_ssize_t]),
    ('GetParent', w.HWND, [w.HWND]),
    ('CreateWindowExW', w.HWND, [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                               c.c_int, c.c_int, c.c_int, c.c_int,
                               w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]),
    ('DestroyWindow', w.BOOL, [w.HWND]),
    ('SetParent', w.HWND, [w.HWND, w.HWND]),
    ('ShowWindow', w.BOOL, [w.HWND, c.c_int]),
    ('SetFocus', w.HWND, [w.HWND]),
    ('GetFocus', w.HWND, []),
    ('SetLayeredWindowAttributes', w.BOOL, [w.HWND, w.DWORD, w.BYTE, w.DWORD]),
    ('SendMessageW', c.c_ssize_t, [w.HWND, w.UINT, w.WPARAM, w.LPARAM]),
):
    function = getattr(user, name)
    function.restype, function.argtypes = result, args
state = {'phase': 0, 'started': time.monotonic(), 'due': 0., 'desktop': None,
         'parent': None, 'tree': '', 'screen': '', 'normal_screen': '', 'normal_tree': ''}


def normal():
    window = next(window for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL')
    identity = native_windows._identity(user, int(window.blui_native_handle))
    assert identity and identity[0] == os.getpid() and identity[3] == 'GHOST_WindowClass'
    return window


def desktop():
    key = state['desktop']
    window = next((window for window in bpy.context.window_manager.windows
                   if (window.as_pointer(), window.blui_native_handle) == key[:2]), None)
    assert window is not None and window.blui_shell_role == 'DESKTOP', 'Owned desktop changed/closed'
    handle = int(window.blui_native_handle)
    identity = native_windows._identity(user, handle)
    assert identity and identity[0] == os.getpid() and identity[3] == 'BLUI_DesktopWindowClass'
    assert int(user.GetPropW(handle, 'BLUI.DesktopHost.v1') or 0) == 1
    assert int(user.GetPropW(handle, 'BLUI.DesktopInstance.v1') or 0) == key[2]
    return window, handle


def create_desktop():
    before = {window.as_pointer() for window in bpy.context.window_manager.windows}
    with bpy.context.temp_override(window=normal()):
        assert bpy.ops.wm.blui_shell_window_create(role='DESKTOP', width=600, height=400) == {'FINISHED'}
    dpi_qa.unchanged()
    added = [window for window in bpy.context.window_manager.windows if window.as_pointer() not in before]
    assert len(added) == 1 and added[0].blui_shell_role == 'DESKTOP'
    window = added[0]
    handle = int(window.blui_native_handle)
    token = int(user.GetPropW(handle, 'BLUI.DesktopInstance.v1') or 0)
    assert token and not user.IsWindowVisible(handle), 'Unattached desktop must start hidden'
    state['desktop'] = (window.as_pointer(), window.blui_native_handle, token)
    desktop()
    assert not user.GetClassLongPtrW(handle, -26) & (0x20 | 0x40 | 0x80), 'Desktop class must allow LAYERED'
    assert window.screen.is_temporary and len(window.screen.areas) == 1
    area = window.screen.areas[0]
    assert area.type == 'NODE_EDITOR'
    tree = bpy.data.node_groups.new('Native Desktop QA', model.TREE)
    space = area.spaces.active
    space.tree_type, space.node_tree, space.pin = model.TREE, tree, True
    space.show_region_ui = space.show_region_toolbar = False
    for index in range(2):
        node = tree.nodes.new(model.NOTE)
        node.location = (index * 250., 0.)
        node.select = False
    state['tree'], state['screen'] = tree.name, window.screen.name
    return token


def close_desktop():
    window, _handle = desktop()
    with bpy.context.temp_override(window=window):
        assert bpy.ops.wm.window_close(force_close=True) == {'FINISHED'}
    state['desktop'] = None


def parent_owned():
    handle, identity = state['parent']
    assert identity[0] == os.getpid() and identity[3].casefold() == 'static'
    assert native_windows._identity(user, handle) == identity, 'Only own exact fake parent may be mutated'
    return handle


def cleanup():
    # Parent destruction queues child RNA cleanup; this fixture never targets Explorer.
    if state['parent'] is not None:
        user.DestroyWindow(parent_owned())
        state['parent'] = None
    for window in list(bpy.context.window_manager.windows):
        if window.blui_shell_role == 'DESKTOP' and int(window.blui_native_handle or '0'):
            identity = native_windows._identity(user, int(window.blui_native_handle))
            if identity and identity[0] == os.getpid() and identity[3] == 'BLUI_DesktopWindowClass':
                with bpy.context.temp_override(window=window):
                    bpy.ops.wm.window_close(force_close=True)


def finish(code):
    try:
        cleanup()
    except Exception:
        traceback.print_exc()
        code = 1
    temporary.cleanup()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def tick():
    try:
        if time.monotonic() - state['started'] > 45:
            raise TimeoutError('Desktop native lifecycle QA exceeded 45 seconds')
        if time.monotonic() < state['due']:
            return .05
        phase = state['phase']
        if phase == 0:
            window = normal()
            area = window.screen.areas[0]
            area.type = 'NODE_EDITOR'
            tree = bpy.data.node_groups.new('Ordinary Node Must Survive', model.TREE)
            area.spaces.active.tree_type, area.spaces.active.node_tree = model.TREE, tree
            state['normal_screen'], state['normal_tree'] = window.screen.name, tree.name
            first = create_desktop()
            close_desktop()
            second = create_desktop()
            assert second != first, 'New desktop must not inherit a stale native instance token'
            window, handle = desktop()
            user.SendMessageW(handle, 0x85, 1, 0)  # WM_NCPAINT must NOT be treated as NCDESTROY.
            state['phase'], state['due'] = 1, time.monotonic() + .25
        elif phase == 1:
            window, handle = desktop()
            assert not user.IsWindowVisible(handle)
            # Only this new OWN fake parent matches the new Desktop context;
            # native DESKTOP creation itself runs from the untouched UI context.
            with dpi_qa.matching_owned_window(handle):
                parent = int(user.CreateWindowExW(0x80, 'STATIC', 'BLUI Owned Desktop Parent QA',
                    0x80000000 | 0x02000000, 100, 100, 640, 440, None, None, None, None) or 0)
            dpi_qa.unchanged()
            dpi_qa.compatible(handle, parent)
            identity = native_windows._identity(user, parent)
            assert parent and identity and identity[0] == os.getpid()
            state['parent'] = (parent, identity)
            user.SetWindowLongPtrW(handle, -16, (user.GetWindowLongPtrW(handle, -16) & ~0x80000000) | 0x40000000)
            user.SetParent(handle, parent_owned())
            assert user.GetParent(handle) == parent, 'Same-DPI own parent attach failed'
            user.SetWindowLongPtrW(handle, -20, user.GetWindowLongPtrW(handle, -20) | 0x80000)
            assert user.SetLayeredWindowAttributes(handle, 0, 255, 2), 'Own raised/layered Desktop rejected'
            user.ShowWindow(parent_owned(), 4)
            user.ShowWindow(handle, 4)
            user.SendMessageW(handle, 0x201, 1, (100 << 16) | 100)  # Explicit own ButtonDown.
            assert user.GetFocus() == handle, 'Child click must focus its own interactive desktop'
            user.SendMessageW(handle, 0x202, 0, (100 << 16) | 100)
            region = next(region for region in window.screen.areas[0].regions if region.type == 'WINDOW')
            with bpy.context.temp_override(window=window, area=window.screen.areas[0], region=region):
                bpy.ops.node.view_all()
            state['phase'], state['due'] = 2, time.monotonic() + .4
        elif phase == 2:
            window, handle = desktop()
            assert user.IsWindowVisible(handle) and user.GetFocus() == handle
            region = next(region for region in window.screen.areas[0].regions if region.type == 'WINDOW')
            point = (region.x + region.width // 2, region.y + region.height // 2)
            window.event_simulate(type='MOUSEMOVE', value='NOTHING',
                                  x=point[0], y=point[1])
            # Every simulated event sets xy explicitly in rna_wm_api.c; omitted
            # key coordinates default to (0,0), not the previous mouse position.
            event = window.event_simulate(type='A', value='PRESS', x=point[0], y=point[1])
            print('DESKTOP_KEY_INPUT:', {'focus': int(user.GetFocus() or 0), 'handle': handle,
                  'region': (region.x, region.y, region.width, region.height),
                  'point': point, 'event': (event.mouse_x, event.mouse_y)}, flush=True)
            window.event_simulate(type='A', value='RELEASE', x=point[0], y=point[1])
            state['phase'], state['due'] = 3, time.monotonic() + .3
        elif phase == 3:
            window, handle = desktop()
            tree = bpy.data.node_groups[state['tree']]
            region = next(region for region in window.screen.areas[0].regions if region.type == 'WINDOW')
            with bpy.context.temp_override(window=window, area=window.screen.areas[0], region=region):
                print('DESKTOP_KEY_RESULT:', {'focus': int(user.GetFocus() or 0), 'handle': handle,
                      'poll': bpy.ops.node.select_all.poll(),
                      'selection': [(node.name, node.select) for node in tree.nodes]}, flush=True)
                assert bpy.ops.screen.screenshot(filepath='D:/BlenderUI/build/desktop-native-own-child.png') == {'FINISHED'}
            assert all(node.select for node in tree.nodes), 'Focused native Desktop Node keyboard event was lost'
            print('PASS hidden ctor/unique instance/NCPAINT gate/layered own child/focus/Node event', flush=True)
            # Queue ordinary messages before parent death; no stale event may redraw/resize dead HWND.
            user.SendMessageW(handle, 0x5, 0, (400 << 16) | 600)
            assert user.DestroyWindow(parent_owned())
            state['parent'] = None
            assert not user.IsWindow(handle)
            state['dead_screen'], state['dead_handle'] = state['screen'], handle
            state['desktop'] = None  # Do not retain old RNA across queued force-close.
            state['phase'], state['due'] = 4, time.monotonic() + .4
        elif phase == 4:
            assert not any(window.blui_shell_role == 'DESKTOP' for window in bpy.context.window_manager.windows)
            assert bpy.data.screens.get(state['dead_screen']) is None, 'Dead private host layout was not removed'
            assert bpy.data.screens.get(state['normal_screen']) is not None
            assert bpy.data.node_groups.get(state['normal_tree']) is not None
            print('PASS owned fake-parent destruction force-cleans only temporary Desktop and keeps normal Node', flush=True)
            create_desktop()
            state['saved_host_screen'] = state['screen']
            path = str(Path(temporary.name) / 'normal-node-with-hidden-desktop.blend')
            with bpy.context.temp_override(window=normal()):
                assert bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, check_existing=False) == {'FINISHED'}
            state['desktop'] = None
            state['phase'], state['due'] = 5, time.monotonic() + .4
            # Never retain context overrides or Window/Area across replacement of Main.
            assert bpy.ops.wm.open_mainfile(filepath=path, load_ui=True) == {'FINISHED'}
        elif phase == 5:
            assert all(window.blui_shell_role == 'NORMAL' for window in bpy.context.window_manager.windows)
            assert bpy.data.screens.get(state['saved_host_screen']) is None
            assert bpy.data.screens.get(state['normal_screen']) is not None
            assert bpy.data.node_groups.get(state['normal_tree']) is not None
            assert normal().screen.areas[0].type == 'NODE_EDITOR'
            print('PASS temporary Desktop screen/layout/window omitted from Blend; ordinary Node retained', flush=True)
            print('check_desktop_native_lifecycle: PASS', flush=True)
            finish(0)
        return .05
    except Exception:
        traceback.print_exc()
        finish(1)


bpy.app.timers.register(tick, first_interval=.5, persistent=True)
