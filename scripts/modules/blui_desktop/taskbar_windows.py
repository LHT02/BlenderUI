# SPDX-License-Identifier: GPL-2.0-or-later
"""Own native role windows, per-display placement and menu lifecycle; no draw-time OS work."""
import os
import sys
import time
import bpy
from . import monitors, runtime, taskbar, taskbar_groups, taskbar_settings, window_placement
from .taskbar_appbar import AppBarController, is_fullscreen
from blui_explorer.localization import iface

_bindings = {}
_topology = ''
_alignment = 'CENTER'
_all_displays = True
_all_tasks = True
_pending = False
_menus = {}
_pending_menus = {}
_keymaps = []
_appbar = AppBarController()
_reserve_due = 0.0
_SHELL_ROLES = {'TASKBAR', 'STARTMENU', 'TASK_CHOOSER', 'TASK_PREVIEW'}


def alignment():
    return _alignment


def set_alignment(value):
    global _alignment
    if value not in ('LEFT', 'CENTER'):
        raise ValueError('Invalid taskbar alignment')
    _alignment = value
    redraw()


def show_all_tasks():
    return _all_tasks


def set_show_all_tasks(value):
    global _all_tasks
    _all_tasks = bool(value)
    redraw()


def all_displays():
    return _all_displays


def _system_hidden():
    state = taskbar.snapshot()
    return state.get('enabled') is True and state.get('hidden_count', 0) > 0


def _geometry_key(snapshot):
    return (monitors.topology_key(snapshot) + ('#hidden' if _system_hidden() else '#visible') +
            '#ui-scale:' + str(bpy.context.preferences.view.ui_scale) +
            '#appearance:' + str(taskbar_settings.values()))


def bar_rect(display, *, system_hidden=False):
    # Monitor DPI is applied by the pure geometry helper; add only the user's
    # Blender display multiplier here, not system.ui_scale (which includes DPI).
    height = taskbar_settings.values()['height'] * bpy.context.preferences.view.ui_scale
    return taskbar_groups.bar_rect(display, height=height, system_hidden=system_hidden)


def _screen_bar_place(window, rect):
    """Position an owned bar at the approved physical edge without changing z-order."""
    if not window.blui_is_taskbar or os.name != 'nt':
        raise ValueError('Only an owned taskbar can use the physical display edge')
    rect = monitors._rect(rect)
    handle, user = window_placement._handle(window.blui_native_handle), window_placement._api()
    identity = window_placement._own(user, handle)
    extended = user.GetWindowLongPtrW(handle, -20)
    if (not extended & 0x80 or not extended & 0x08000000 or
            window_placement._own(user, handle) != identity):
        raise RuntimeError('The BLUI taskbar identity changed')
    if not user.SetWindowPos(handle, None, rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1],
                             0x4000 | 0x10 | 0x200 | 0x4):
        raise OSError('Unable to position the BLUI taskbar')


def needs_service():
    return _pending or bool(role_windows())


def _identity(window):
    return (window.as_pointer(), window.blui_native_handle)


def role_windows(role=None):
    return [window for window in bpy.context.window_manager.windows
            if window.blui_shell_role in _SHELL_ROLES and (role is None or window.blui_shell_role == role)
            and window.blui_native_handle != '0']


def device(window):
    return _bindings.get(_identity(window), '')


def native_handles():
    return [window.blui_native_handle for window in bpy.context.window_manager.windows
            if window.blui_shell_role != 'NORMAL' and window.blui_native_handle != '0']


def redraw():
    for window in role_windows():
        for area in window.screen.areas:
            area.tag_redraw()


def create(context, role, width, height, *, no_activate=False):
    if role not in ('TASKBAR', 'STARTMENU', 'TASK_CHOOSER', 'TASK_PREVIEW'):
        raise ValueError('Invalid native shell window role')
    if type(no_activate) is not bool or (no_activate and role != 'TASK_CHOOSER'):
        raise ValueError('Only an explicit task chooser tooltip may be passive')
    before = {window.as_pointer() for window in context.window_manager.windows}
    arguments = {'role': role, 'width': width, 'height': height}
    if no_activate:
        arguments['no_activate'] = True  # Older binaries fail closed, never steal foreground focus.
    result = bpy.ops.wm.blui_shell_window_create(**arguments)
    created = [window for window in context.window_manager.windows if window.as_pointer() not in before]
    if result != {'FINISHED'} or len(created) != 1 or created[0].blui_shell_role != role:
        raise RuntimeError(iface('Could not open a taskbar window'))
    return created[0]


def _topmost(window):
    # A fresh bpy role window is required, never an arbitrary/cached OS handle.
    if os.name != 'nt' or window.blui_shell_role not in _SHELL_ROLES:
        return
    if window.blui_is_taskbar and is_fullscreen(window):
        return
    handle = window_placement._handle(window.blui_native_handle)
    user = window_placement._api()
    identity = window_placement._own(user, handle)
    if window_placement._own(user, handle) != identity:
        raise RuntimeError('The BLUI shell window changed')
    # ASYNC | NOSIZE | NOMOVE | NOACTIVATE | NOOWNERZORDER. No foreign windows.
    if not user.SetWindowPos(handle, -1, 0, 0, 0, 0, 0x4000 | 0x1 | 0x2 | 0x10 | 0x200):
        raise OSError('Unable to position the BLUI taskbar')


def close_window(window):
    # Revalidate membership and role immediately; don't close reused RNA pointers.
    key = _identity(window)
    current = next((item for item in role_windows() if _identity(item) == key), None)
    if current is None:
        return False
    hover = sys.modules.get('blui_desktop.shell_hover')
    if hover is not None:
        hover.closed(current)
    if current.blui_is_taskbar:
        _appbar.close_window(current)
    _bindings.pop(key, None)
    _menus.pop(key, None)
    _pending_menus.pop(key, None)
    area = next(iter(current.screen.areas), None)
    region = next((item for item in area.regions if item.type == 'WINDOW'), None) if area else None
    with bpy.context.temp_override(window=current, area=area, region=region):
        return bpy.ops.wm.window_close(force_close=True) == {'FINISHED'}


def open_for_displays(context, snapshot=None, *, all_displays=True):
    global _all_displays, _pending, _topology
    snapshot = monitors.validate(snapshot or runtime.monitor_snapshot())
    rows = snapshot['monitors']
    if not rows:
        _pending = True
        _all_displays = bool(all_displays)
        return []
    if not all_displays:
        rows = [next((row for row in rows if row['primary']), rows[0])]
    _all_displays, _pending = bool(all_displays), True
    wanted, result = {row['device'] for row in rows}, []
    for row in rows:
        window = next((window for window in role_windows('TASKBAR') if device(window) == row['device']), None)
        hidden = _system_hidden()
        rect = bar_rect(row, system_hidden=hidden)
        created = window is None
        if created:
            window = create(context, 'TASKBAR', rect[2] - rect[0], rect[3] - rect[1])
            _bindings[_identity(window)] = row['device']
        try:
            if hidden:
                _screen_bar_place(window, rect)
            else:
                window_placement.place(window.blui_native_handle, rect, snapshot, preferred=row['device'])
            _topmost(window)
        except Exception:
            if created:
                close_window(window)
            raise
        result.append(window)
    for window in role_windows('TASKBAR'):
        if device(window) not in wanted:
            close_window(window)
    _reserve(result, snapshot)
    _topology = _geometry_key(snapshot)
    _pending = False
    return result


def _reserve(windows, snapshot):
    global _reserve_due
    from . import session
    if session.disable_for_tests:
        return
    _reserve_due = time.monotonic() + .5
    height = taskbar_settings.values()['height'] * bpy.context.preferences.view.ui_scale
    rects = _appbar.reconcile({device(window): window for window in windows}, snapshot, height)
    for window in windows:
        rect = rects.get(device(window))
        if rect and window_placement.bounds(window.blui_native_handle)['rect'] != rect:
            _screen_bar_place(window, rect)


def request_open(*, all_displays=True):
    global _pending, _all_displays
    _pending, _all_displays = True, bool(all_displays)


def tick(snapshot):
    global _topology
    snapshot = monitors.validate(snapshot)
    alive = {_identity(window) for window in role_windows()}
    for mapping in (_bindings, _menus, _pending_menus):
        for key in list(mapping):
            if key not in alive:
                mapping.pop(key, None)
    key = _geometry_key(snapshot)
    changed = key != _topology
    if (changed or _pending) and runtime.interaction_busy(None):
        # Keep the old topology key so hotplug/size changes are retried once
        # native interaction releases its Window/Area references.
        return
    if (_pending or (role_windows('TASKBAR') and key != _topology)) and snapshot['monitors']:
        if not runtime.interaction_busy(None):
            open_for_displays(bpy.context, snapshot, all_displays=_all_displays)
    if changed:
        for window in role_windows():
            if window.blui_shell_role != 'TASKBAR':
                try:
                    window_placement.recover(window.blui_native_handle, snapshot, preferred=device(window))
                except (ValueError, OSError, RuntimeError):
                    pass
        _topology = key
    if snapshot['monitors']:
        if role_windows('TASKBAR') and time.monotonic() >= _reserve_due:
            _reserve(role_windows('TASKBAR'), snapshot)
        for key, (source_key, width, height) in list(_pending_menus.items()):
            window = next((window for window in role_windows() if _identity(window) == key), None)
            if window is None:
                _pending_menus.pop(key, None)
                continue
            source = next((item for item in bpy.context.window_manager.windows if _identity(item) == source_key), None)
            place_menu(window, source, width, height)


def place_menu(window, source_window, width, height, *, anchor_x=None, focus=True, scale_ui=True):
    if window.blui_shell_role not in ('STARTMENU', 'TASK_CHOOSER', 'TASK_PREVIEW'):
        raise ValueError('Only an owned shell menu can be placed above the taskbar')
    snapshot = monitors.validate(runtime.monitor_snapshot())
    rows = snapshot['monitors']
    if not rows:
        # First invocation from Files may precede the background monitor snapshot.
        # Keep only immutable identities, never RNA pointers across this wait.
        _pending_menus[_identity(window)] = (_identity(source_window) if source_window else None, width, height)
        focus_window(window)
        return False
    source_device = device(source_window) if source_window else ''
    display = next((row for row in rows if row['device'] == source_device),
                   next((row for row in rows if row['primary']), rows[0]))
    bar = bar_rect(display, system_hidden=_system_hidden())
    source_bar = next((item for item in role_windows('TASKBAR') if device(item) == display['device']), None)
    if source_bar is not None:
        bar = window_placement.bounds(source_bar.blui_native_handle)['rect']
    anchor = [bar[0], bar[1]]
    if scale_ui:
        scale = bpy.context.preferences.view.ui_scale
        width, height = width * scale, height * scale
    if anchor_x is not None:
        anchor[0] = int(anchor_x)
    elif _alignment == 'CENTER' and window.blui_shell_role != 'STARTMENU':
        anchor[0] = (bar[0] + bar[2]) // 2 - round(width * display['dpi'][0] / 192)
    rect = taskbar_groups.menu_rect(display, anchor, width, height)
    window_placement.place(window.blui_native_handle, rect, snapshot, preferred=display['device'])
    _bindings[_identity(window)] = display['device']
    _pending_menus.pop(_identity(window), None)
    _topmost(window)
    if focus:
        focus_window(window)
    return True


def focus_window(window):
    if window.blui_shell_role not in ('STARTMENU', 'TASK_CHOOSER') or os.name != 'nt':
        return False
    handle = window_placement._handle(window.blui_native_handle)
    user = window_placement._api()
    identity = window_placement._own(user, handle)
    return window_placement._own(user, handle) == identity and bool(user.SetForegroundWindow(handle))


def is_foreground(window):
    if os.name != 'nt':
        return False
    handle = window_placement._handle(window.blui_native_handle)
    user = window_placement._api()
    identity = window_placement._own(user, handle)
    return window_placement._own(user, handle) == identity and user.GetForegroundWindow() == handle


def menu_state(window):
    return _menus.get(_identity(window), {})


def set_menu_state(window, value):
    if window.blui_shell_role not in ('TASK_CHOOSER', 'TASK_PREVIEW') or not isinstance(value, dict):
        raise ValueError('Invalid task chooser window')
    _menus[_identity(window)] = dict(value)
    for area in window.screen.areas:
        area.tag_redraw()


def close(context=None):
    global _pending, _topology
    _pending, _topology = False, ''
    _appbar.close()
    for window in list(role_windows()):
        close_window(window)
    _bindings.clear()
    _menus.clear()
    _pending_menus.clear()


def register():
    configuration = bpy.context.window_manager.keyconfigs.addon
    if not configuration:
        return
    keymap = configuration.keymaps.new(name='BLUI Taskbar', space_type='INFO', region_type='WINDOW')
    item = keymap.keymap_items.new('wm.blui_taskbar_middle', 'MIDDLEMOUSE', 'PRESS')
    _keymaps.append((keymap, item))
    # Capture Shift on press, before UI's deferred button callback can see a
    # later modifier state (or the default Info/View2D maps consume the event).
    item = keymap.keymap_items.new('wm.blui_taskbar_middle', 'LEFTMOUSE', 'PRESS', shift=True)
    _keymaps.append((keymap, item))
    item = keymap.keymap_items.new('wm.blui_shell_context_menu', 'RIGHTMOUSE', 'PRESS')
    _keymaps.append((keymap, item))
    popup = configuration.keymaps.new(name='BLUI Shell Popup', space_type='INFO', region_type='WINDOW')
    item = popup.keymap_items.new('wm.blui_shell_popup_close', 'ESC', 'PRESS')
    _keymaps.append((popup, item))
    item = popup.keymap_items.new('wm.blui_shell_context_menu', 'RIGHTMOUSE', 'PRESS')
    _keymaps.append((popup, item))
    item = popup.keymap_items.new('wm.blui_preview_pick', 'LEFTMOUSE', 'PRESS')
    _keymaps.append((popup, item))


def unregister():
    global _pending
    _pending = False
    for keymap, item in _keymaps:
        keymap.keymap_items.remove(item)
    _keymaps.clear()
    _bindings.clear()
    _menus.clear()
    _pending_menus.clear()
