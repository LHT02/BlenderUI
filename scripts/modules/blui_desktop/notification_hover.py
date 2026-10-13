# SPDX-License-Identifier: GPL-2.0-or-later
"""Debounced, passive notification tips; helper commands/metadata are RAM-only.

Native positioning/identity/property checks occur only in the shell timer.
Drawing never calls Win32, filesystem, snapshot decoding or icon creation.
"""
import ctypes as c
from ctypes import wintypes as w
import itertools
import time
import unicodedata
import bpy
from bpy.types import Panel
from . import notification_client as client, runtime, taskbar_windows
from blui_explorer.localization import iface

KIND = 'NOTIFICATION_TIP'
PROPERTY = 'BLUI.NotificationTip.Instance.v1'
DEBOUNCE = .35
_serial = itertools.count(1)
_candidate = _entered = _popup = _suppressed = None
_since = 0.0
_point = (0, 0)
_lines = ()
_icon = 0
_error = ''
_closing = False
_layout_key = None


def error():
    return _error


def _pair(window):
    return window.as_pointer(), window.blui_native_handle


def _signature(row):
    return tuple(row.get(field) for field in ('key', 'handle', 'uid', 'guid', 'pid', 'thread_id',
        'process_started', 'window_class', 'callback', 'version', 'backend', 'toolbar_handle', 'toolbar_thread'))


def _row(key, value):
    if not value.get('enabled'):
        return None
    for row in value.get('icons', ()):
        if row.get('key') == key:
            return row
    for item in value.get('controls', ()):
        if key == 'system:' + item['key']:
            return dict(item, key=key, tip=iface(item['label']), cache_key='')
    return None


def _actions(row):
    return row.get('actions', ('HOVER_ENTER', 'HOVER_LEAVE') if row.get('callback') else ())


def tip_lines(text, width=64):
    """Bounded Unicode wrapping; metadata is at most 127 chars, labels use RAM."""
    result, line, count = [], '', 0
    for character in text[:384]:
        size = 2 if unicodedata.east_asian_width(character) in {'W', 'F'} else 1
        if character == '\n' or (count + size > width and line):
            result.append(line)
            line, count = '', 0
            if len(result) == 6:
                return tuple(result)
            if character == '\n':
                continue
        line += character
        count += size
    if line:
        result.append(line)
    return tuple(result or [iface('Notification Icon')])


def _text(row):
    value = row.get('tip') or iface('Notification Icon')
    if row.get('backend') == 'UIA':
        value += '\n' + iface('Historical icon: default action only')
    elif row.get('backend') == 'DISPLAY':
        value += '\n' + iface('Historical icon: use Original Windows Notification Area')
    return value


def _user():
    user = taskbar_windows.window_placement._api()
    for name, result, args in (
        ('GetPropW', w.HANDLE, [w.HWND, w.LPCWSTR]),
        ('SetPropW', w.BOOL, [w.HWND, w.LPCWSTR, w.HANDLE]),
    ):
        function = getattr(user, name)
        function.restype, function.argtypes = result, args
    return user


def _owned_ram(window):
    if _popup is None or window.blui_shell_role != 'TASK_CHOOSER' or _pair(window) != _popup[0]:
        return False
    state = taskbar_windows.menu_state(window)
    return state.get('kind') == KIND and state.get('hover_owner') == _popup[2]


def _live_popup():
    if _popup is None:
        return None
    window = next((window for window in taskbar_windows.role_windows('TASK_CHOOSER')
                   if _owned_ram(window)), None)
    if window is None:
        return None
    user, handle = _user(), int(window.blui_native_handle)
    identity = taskbar_windows.window_placement._own(user, handle)
    if (identity != _popup[1] or int(user.GetPropW(handle, PROPERTY) or 0) != _popup[2] or
            taskbar_windows.window_placement._own(user, handle) != identity):
        return None  # A reused HWND or a chooser taken over by another menu is NOT ours.
    return window


def _send(token, action, point):
    row = _row(token[2], client.snapshot())
    if row is None or _signature(row) != token[3] or action not in _actions(row):
        return False
    x, y = (max(-32768, min(32767, int(value))) for value in point)
    try:
        return client.command(token[2], action, x, y)
    except (OSError, RuntimeError, ValueError):
        return False  # Gone/stale/unsupported callbacks are never guessed/retried blindly.


def _leave():
    global _entered
    token, _entered = _entered, None
    if token is not None:
        _send(token, 'HOVER_LEAVE', _point)


def _close_tip():
    global _popup, _lines, _icon, _closing, _layout_key
    try:
        window = _live_popup()
    except (OSError, RuntimeError, ValueError, ReferenceError):
        window = None
    _popup, _lines, _icon = None, (), 0
    _layout_key = None
    if window is not None:
        _closing = True
        try:
            taskbar_windows.close_window(window)
        finally:
            _closing = False


def close():
    """Event-boundary shutdown/cancel: own tooltip only; a supported LEAVE at most once."""
    global _candidate, _suppressed
    _leave()
    _candidate = _suppressed = None
    _close_tip()


def closed(window):
    global _candidate, _popup, _suppressed, _lines, _icon
    if _closing:
        return
    if _owned_ram(window):
        _suppressed = _candidate  # An explicit ESC/close should not instantly reopen it.
        _leave()
        _candidate, _popup, _lines, _icon = None, None, (), 0
    elif _candidate and window.blui_shell_role == 'TASKBAR' and _pair(window) == _candidate[:2]:
        close()


def _blocked():
    return (bool(taskbar_windows.role_windows('STARTMENU')) or
            bool(taskbar_windows.role_windows('TASK_PREVIEW')) or
            any(not _owned_ram(window) for window in taskbar_windows.role_windows('TASK_CHOOSER')))


def _pick(point, inside):
    for bar in taskbar_windows.role_windows('TASKBAR'):
        if not inside(bar, point):
            continue
        area = bar.screen.areas[0]
        region = next((region for region in area.regions if region.type == 'WINDOW'), None)
        if region is None:
            return None
        with bpy.context.temp_override(window=bar, area=area, region=region):
            hovered = getattr(bpy.context, 'blui_shell_hover_button', None)
            key = str(hovered.key) if hovered and hovered.bl_rna.identifier == 'WM_OT_blui_notification_action' else ''
        row = _row(key, client.snapshot()) if key else None
        if row is not None:
            return (*_pair(bar), key, _signature(row)), bar, row
        return None
    return None


def _show(source, row, point):
    global _popup, _lines, _icon, _layout_key
    display = next((row for row in runtime.monitor_snapshot()['monitors']
                    if row['device'] == taskbar_windows.device(source)), None)
    if display is None:
        return
    lines = tip_lines(_text(row))
    cells = max(sum(2 if unicodedata.east_asian_width(char) in {'W', 'F'} else 1 for char in line)
                for line in lines)
    width, height = max(200, min(520, cells * 7 + 32)), 24 + 20 * len(lines)
    window = _live_popup()
    if window is None:
        scale = display['dpi'][0] / 96 * bpy.context.preferences.view.ui_scale
        with bpy.context.temp_override(window=source):
            window = taskbar_windows.create(bpy.context, 'TASK_CHOOSER', round(width * scale),
                                            round(height * scale), no_activate=True)
        handle, user = int(window.blui_native_handle), _user()
        identity = taskbar_windows.window_placement._own(user, handle)
        serial = next(_serial)
        if not user.GetWindowLongPtrW(handle, -20) & 0x08000000:
            taskbar_windows.close_window(window)
            raise RuntimeError('Notification tooltip must be a passive native window')
        if (taskbar_windows.window_placement._own(user, handle) != identity or
                not user.SetPropW(handle, PROPERTY, serial)):
            taskbar_windows.close_window(window)
            raise RuntimeError('Notification tooltip ownership could not be installed')
        _popup = (_pair(window), identity, serial)
        taskbar_windows.set_menu_state(window, {'kind': KIND, 'hover_owner': serial,
                                               'device': taskbar_windows.device(source)})
    _lines, _icon = lines, client.icon_value(row)
    geometry = (_pair(source), tuple(display['work']), tuple(display['dpi']),
                bpy.context.preferences.view.ui_scale, width, height)
    if geometry != _layout_key:
        taskbar_windows.place_menu(window, source, width, height,
                                  anchor_x=point[0] - round(width * display['dpi'][0] / 192), focus=False)
        _layout_key = geometry  # Stable hover does not continuously move/re-stack its HWND.
    for area in window.screen.areas:
        area.tag_redraw()


def tick(cursor_provider):
    """Called before preview gating; never retains RNA across a native window close."""
    global _candidate, _entered, _since, _suppressed, _point, _error
    from .shell_hover import inside
    try:
        point = cursor_provider()
        if point is not None:
            _point = point
        if _popup is not None and _live_popup() is None:
            _suppressed = _candidate
            _leave()
            _close_tip()
        if runtime.shell_interaction_busy() or _blocked():
            close()
            return
        picked = _pick(point, inside) if point is not None else None
        candidate = picked[0] if picked else None
        if _suppressed != candidate:
            _suppressed = None
        if candidate != _candidate:
            _leave()
            _close_tip()
            _candidate, _since = candidate, time.monotonic()
        if candidate is None or candidate == _suppressed or time.monotonic() - _since < DEBOUNCE:
            return
        if _entered is None and _send(candidate, 'HOVER_ENTER', point):
            _entered = candidate
        _show(picked[1], picked[2], point)
        _error = ''
    except (OSError, RuntimeError, ValueError, ReferenceError, TypeError, AttributeError) as exc:
        _error = str(exc)[:256]
        close()


class BLUI_PT_notification_tip(Panel):
    bl_space_type = 'INFO'
    bl_region_type = 'WINDOW'
    bl_label = 'Notification Icon'
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        return bool(context.window and _owned_ram(context.window))

    def draw(self, _context):
        for index, text in enumerate(_lines):
            kwargs = {'icon_value': _icon} if index == 0 and _icon else {}
            self.layout.label(text=text, translate=False, **kwargs)


classes = (BLUI_PT_notification_tip,)
