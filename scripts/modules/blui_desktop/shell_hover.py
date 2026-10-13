# SPDX-License-Identifier: GPL-2.0-or-later
"""Debounced native task previews; OS work is timer-only, drawing reads memory."""
import ctypes as c
from ctypes import wintypes as w
import os
import time
import bpy
from bpy.types import Operator, Panel
from . import notification_hover, runtime, taskbar_actions, taskbar_windows
from .taskbar_previews import PreviewController, _source
from .taskbar_preview_layout import preview_layout
from blui_explorer.localization import iface

_controller = PreviewController()
_candidate = None
_since = 0.0
_leave_due = 0.0
_shown = None
_geometry = None
_rows = ()
_targets = ()
_updated = 0.0


def cursor():
    if os.name != 'nt':
        return None
    user = c.WinDLL('user32', winmode=0x800, use_last_error=True)
    user.GetCursorPos.argtypes, user.GetCursorPos.restype = [c.POINTER(w.POINT)], w.BOOL
    point = w.POINT()
    return (point.x, point.y) if user.GetCursorPos(c.byref(point)) else None


def inside(window, point):
    if not point:
        return False
    rect = taskbar_windows.window_placement.bounds(window.blui_native_handle)['rect']
    return rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]


def preview_window():
    return next(iter(taskbar_windows.role_windows('TASK_PREVIEW')), None)


def closed(window):
    global _shown, _geometry, _rows, _targets
    notification_hover.closed(window)
    if window.blui_shell_role == 'TASK_PREVIEW':
        _controller.close()
        _shown, _geometry, _rows = None, None, ()
        _targets = ()


def close():
    global _candidate
    _candidate = None
    window = preview_window()
    if window is not None:
        taskbar_windows.close_window(window)
    else:
        _controller.close()


def tick():
    global _candidate, _since, _leave_due, _shown, _geometry, _rows, _updated, _targets
    notification_hover.tick(cursor)
    if runtime.shell_interaction_busy():
        return
    point, now = cursor(), time.monotonic()
    window = preview_window()
    over_preview = window is not None and inside(window, point)
    if over_preview:
        _leave_due = now + .4
    selected, source = None, None
    if over_preview and _shown:
        source = next((bar for bar in taskbar_windows.role_windows('TASKBAR')
                       if (bar.as_pointer(), bar.blui_native_handle) == _shown[:2]), None)
        if source is None:
            # Hovering the popup must not keep registrations alive after its
            # source bar disappears (for example a disconnected monitor).
            close()
            return
        selected = _shown[2] if source else None
    # Native press hit-testing uses the queued event; hover explicitly uses the
    # latest mouse state, but only after the real pointer is inside that HWND.
    for bar in taskbar_windows.role_windows('TASKBAR'):
        if over_preview:
            break
        if not inside(bar, point):
            continue
        area = bar.screen.areas[0]
        region = next(item for item in area.regions if item.type == 'WINDOW')
        with bpy.context.temp_override(window=bar, area=area, region=region):
            hovered = getattr(bpy.context, 'blui_shell_hover_button', None)
            if hovered and hovered.bl_rna.identifier == 'WM_OT_blui_taskbar_group':
                selected = hovered.key
                source = bar
        break
    candidate = (source.as_pointer(), source.blui_native_handle, selected) if source and selected else None
    if candidate != _candidate:
        _candidate, _since = candidate, now
    if candidate is None:
        if window is not None and now >= _leave_due:
            close()
        return
    _leave_due = now + .4
    if now - _since < .35 or taskbar_windows.role_windows('TASK_CHOOSER') or taskbar_windows.role_windows('STARTMENU'):
        return
    group = taskbar_actions.find_group(selected, source)
    if not group:
        close()
        return
    if _shown == candidate and now - _updated < .4:
        return
    display = next((row for row in runtime.monitor_snapshot()['monitors']
                    if row['device'] == taskbar_windows.device(source)), None)
    if not display:
        return
    dpi_scale = display['dpi'][0] / 96
    scale = dpi_scale * bpy.context.preferences.view.ui_scale
    geometry = preview_layout(len(group['tasks']), display['work'][2] - display['work'][0], scale=scale)
    if window is None:
        with bpy.context.temp_override(window=source):
            window = taskbar_windows.create(bpy.context, 'TASK_PREVIEW', geometry['width'], geometry['height'])
    if _shown != candidate or geometry != _geometry:
        taskbar_windows.place_menu(window, source, geometry['width'] / dpi_scale,
            geometry['height'] / dpi_scale, anchor_x=point[0] - geometry['width'] // 2,
            focus=False, scale_ui=False)
    _geometry = geometry
    _rows = _controller.update(window, group['tasks'][:geometry['count']], geometry['rects'],
                               excluded=taskbar_windows.native_handles())
    _targets = tuple(_source(task) for task in group['tasks'][:geometry['count']])
    taskbar_windows.set_menu_state(window, {'kind': 'PREVIEW', 'key': group['key'],
                                          'device': taskbar_windows.device(source)})
    _shown, _updated = candidate, now


class WM_OT_blui_preview_pick(Operator):
    bl_idname = 'wm.blui_preview_pick'
    bl_label = 'Activate Window Preview'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return bool(context.window and context.window.blui_shell_role == 'TASK_PREVIEW')

    def invoke(self, context, event):
        if not _geometry:
            return {'CANCELLED'}
        state = taskbar_windows.menu_state(context.window)
        group = taskbar_actions.find_group(state.get('key', ''), monitor=state.get('device', ''))
        if not group:
            close()
            return {'CANCELLED'}
        y = context.window.height - event.mouse_y
        for index, rect in enumerate(_geometry['card_rects']):
            if rect[0] <= event.mouse_x < rect[2] and rect[1] <= y < rect[3]:
                token = _targets[index] if index < len(_targets) else None
                target = next((task for task in group['tasks'] if token and _source(task) == token), None)
                if target is None:
                    close()
                    return {'CANCELLED'}
                taskbar_actions.activate(target)
                close()
                return {'FINISHED'}
        return {'CANCELLED'}


class BLUI_PT_task_previews(Panel):
    bl_space_type = 'INFO'
    bl_region_type = 'WINDOW'
    bl_label = 'Window Previews'
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        return bool(context.window and context.window.blui_shell_role == 'TASK_PREVIEW')

    def draw(self, context):
        if not _geometry:
            return
        scale = context.preferences.system.ui_scale
        row = self.layout.row()
        for result in _rows:
            column = row.column()
            column.ui_units_x = (_geometry['card_rects'][0][2] - _geometry['card_rects'][0][0]) / (20 * scale)
            column.label(text=result['title'][:48], translate=False)
            spacer = column.row()
            spacer.ui_units_y = 6.6
            if result['status'] != 'LIVE':
                spacer.label(text=iface('Preview Unavailable'), icon='WINDOW', translate=False)
            else:
                spacer.label(text='')


classes = (WM_OT_blui_preview_pick, BLUI_PT_task_previews)
