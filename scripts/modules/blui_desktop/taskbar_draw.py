# SPDX-License-Identifier: GPL-2.0-or-later
"""Blender-native INFO Header/Panel content for independent taskbar and chooser windows."""
from datetime import datetime
from bpy.types import Header, Panel
from . import icon_cache, runtime, taskbar_groups, taskbar_metrics, taskbar_windows
from .taskbar_actions import current_groups, find_group
from blui_explorer.localization import iface


class BLUI_HT_standalone_taskbar(Header):
    bl_space_type = 'INFO'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        if not context.window.blui_is_taskbar:
            return
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        centered = taskbar_windows.alignment() == 'CENTER'
        if centered:
            balance = layout.row(align=True)
            balance.ui_units_x = taskbar_metrics.SIDE_UNITS
            balance.label(text='')
            layout.separator_spacer()
        body = layout.row(align=True)
        body.operator('wm.blui_start_menu', text='', icon='BLENDER', icon_preview=True)
        rows = current_groups(context.window)
        # A bounded native row never balloons a thin window into a screen-wide
        # text list. Overflow opens a full-height native chooser, not a clipped menu.
        capacity = taskbar_metrics.icon_capacity(context.region.width, context.preferences.system.ui_scale)
        for group in rows[:capacity]:
            icon = icon_cache.value(group['executable'])
            entry = body.row(align=True)
            entry.enabled = any(task.get('actionable') for task in group['tasks'])
            if icon:
                op = entry.operator('wm.blui_taskbar_group', text='', icon_value=icon,
                                    depress=group['active'], icon_preview=True)
            else:
                op = entry.operator('wm.blui_taskbar_group', text='', icon='WINDOW',
                                    depress=group['active'], icon_preview=True)
            op.key = group['key']
        if len(rows) > capacity:
            overflow = body.row(align=True)
            overflow.scale_y = 2
            overflow.operator('wm.blui_taskbar_settings', text='…')
        layout.separator_spacer()
        right = layout.row(align=True)
        right.ui_units_x = taskbar_metrics.SIDE_UNITS
        right.scale_y = 2
        right.operator_context = 'EXEC_DEFAULT'
        right.operator('wm.blui_taskbar_settings', text='', icon='PREFERENCES')
        right.operator('wm.blui_taskbar_settings', text=datetime.now().strftime('%H:%M'), emboss=False, translate=False)


class BLUI_PT_taskbar_chooser(Panel):
    bl_space_type = 'INFO'
    bl_region_type = 'WINDOW'
    bl_label = 'Taskbar'
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        return bool(context.window and context.window.blui_shell_role == 'TASK_CHOOSER')

    def draw(self, context):
        state = taskbar_windows.menu_state(context.window)
        layout = self.layout
        layout.operator_context = 'EXEC_DEFAULT'
        heading = layout.row()
        heading.label(text=iface('Taskbar Settings') if state.get('kind') == 'SETTINGS' else iface('Application Windows'))
        op = heading.operator('wm.window_close', text='', icon='X')
        op.force_close = True
        if state.get('kind') == 'SETTINGS':
            for mode, label in (('LEFT', 'Windows 10: Left'), ('CENTER', 'Windows 11: Center')):
                op = layout.operator('wm.blui_taskbar_layout', text=iface(label),
                                     depress=taskbar_windows.alignment() == mode, translate=False)
                op.mode = mode
            layout.separator()
            for mode, label in (('ALL_DISPLAYS', 'All Displays'), ('PRIMARY_DISPLAY', 'Primary Display'),
                                ('ALL_TASKS', 'All Application Windows'), ('THIS_DISPLAY', 'Windows on This Display')):
                op = layout.operator('wm.blui_taskbar_layout', text=iface(label), translate=False)
                op.mode = mode
            layout.separator()
            for action, label in (('hide', 'Hide Windows Taskbar'), ('restore', 'Restore Windows Taskbar')):
                op = layout.operator('wm.blui_windows_taskbar', text=iface(label), translate=False)
                op.action = action
            layout.operator('wm.blui_taskbar_close', text=iface('Close BLUI Taskbar'), translate=False)
            layout.separator()
            layout.label(text=iface('Shift-click or Middle-click: New Instance'), icon='INFO', translate=False)
            layout.separator()
            layout.label(text=iface('Application Windows'), translate=False)
            groups = current_groups(monitor=state.get('device', ''))
        else:
            group = find_group(state.get('key', ''), monitor=state.get('device', ''))
            groups = [group] if group else []
        for group in groups:
            layout.label(text=group['title'], translate=False)
            for task in group['tasks']:
                row = layout.row(align=True)
                row.enabled = task.get('actionable', False)
                icon = icon_cache.value(group['executable'])
                kwargs = {'icon_value': icon} if icon else {'icon': 'WINDOW'}
                op = row.operator('wm.blui_taskbar_pick', text=task['title'][:100],
                                  depress=task['active'], translate=False, **kwargs)
                op.key, op.handle = group['key'], task['handle']
            if any(taskbar_groups.can_launch(task) for task in group['tasks']):
                op = layout.operator('wm.blui_taskbar_pick', text=iface('New Application Instance'), icon='ADD', translate=False)
                op.key, op.new_instance = group['key'], True
        if not groups and state.get('kind') != 'SETTINGS':
            layout.label(text=iface('This application changed; refresh the taskbar'), icon='INFO', translate=False)
        if runtime.task_error():
            layout.label(text=runtime.task_error(), icon='ERROR', translate=False)


classes = (BLUI_HT_standalone_taskbar, BLUI_PT_taskbar_chooser)
