# SPDX-License-Identifier: GPL-2.0-or-later
"""Shell context actions in independent windows, never inside a thin taskbar."""
import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator
from blui_explorer.localization import iface
from . import start_menu, taskbar_actions, taskbar_windows


class WM_OT_blui_shell_context_menu(Operator):
    bl_idname = 'wm.blui_shell_context_menu'
    bl_label = 'Shell Context Menu'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return bool(context.window and context.window.blui_shell_role in taskbar_windows._SHELL_ROLES)

    def invoke(self, context, event):
        from . import shell_hover
        if context.window.blui_shell_role == 'TASK_PREVIEW':
            # Closing this very context invalidates its Window/Area RNA.
            shell_hover.close()
            return {'FINISHED'}
        shell_hover.close()
        hovered = getattr(context, 'blui_shell_button', None)
        name = hovered.bl_rna.identifier if hovered else ''
        kind, key, app_id = 'SETTINGS', '', ''
        if name == 'WM_OT_blui_notification_action':
            from . import notification_client
            origin = taskbar_windows.window_placement.bounds(context.window.blui_native_handle)['rect']
            try:
                notification_client.command(hovered.key, 'RIGHT',
                    origin[0] + event.mouse_x, origin[3] - event.mouse_y)
            except (OSError, RuntimeError, ValueError) as exc:
                self.report({'WARNING'}, str(exc))
                return {'CANCELLED'}
            return {'FINISHED'}
        if name in {'WM_OT_blui_taskbar_group', 'WM_OT_blui_taskbar_pick'}:
            kind, key = 'TASK_CONTEXT', hovered.key
        elif name == 'WM_OT_blui_start_launch':
            kind, app_id = 'START_APP', hovered.app_id
        elif name == 'WM_OT_blui_start_menu':
            kind = 'START_CONTEXT'
        elif context.window.blui_shell_role == 'STARTMENU':
            # Do not expose Blender's debug/button context menu on system links.
            return {'CANCELLED'}
        source = context.window
        window = next(iter(taskbar_windows.role_windows('TASK_CHOOSER')), None)
        if window is None:
            window = taskbar_windows.create(context, 'TASK_CHOOSER', 420, 360 if kind == 'SETTINGS' else 240)
        taskbar_windows.set_menu_state(window, {'kind': kind, 'key': key, 'app_id': app_id,
            'device': taskbar_windows.device(source),
            'source': (source.as_pointer(), source.blui_native_handle)})
        origin = taskbar_windows.window_placement.bounds(source.blui_native_handle)['rect']
        taskbar_windows.place_menu(window, source, 420,
                                   700 if kind == 'SETTINGS' else 240,
                                   anchor_x=origin[0] + event.mouse_x)
        return {'FINISHED'}


class WM_OT_blui_task_context_action(Operator):
    bl_idname = 'wm.blui_task_context_action'
    bl_label = 'Application Window Action'
    key: StringProperty(options={'SKIP_SAVE'})
    action: EnumProperty(items=(('ACTIVATE', 'Activate Window', ''), ('MINIMIZE', 'Minimize Window', ''),
                                ('NEW', 'New Application Instance', ''), ('CLOSE', 'Close Window', '')))

    def execute(self, context):
        group = taskbar_actions.find_group(self.key, monitor=taskbar_windows.device(context.window))
        if not group:
            return {'CANCELLED'}
        if self.action == 'NEW':
            taskbar_actions.launch_group(group)
        else:
            from . import native_windows
            for task in group['tasks']:
                if not task.get('actionable'):
                    continue
                if self.action == 'CLOSE':
                    native_windows.close_task(task)
                elif self.action == 'MINIMIZE':
                    native_windows.act(task['handle'], task['pid'], minimize=True,
                        identity=(task['thread_id'], task['process_started'], task['window_class']))
                else:
                    taskbar_actions.activate(task)
                    break
        taskbar_windows.close_window(context.window)
        return {'FINISHED'}


class WM_OT_blui_start_context_action(Operator):
    bl_idname = 'wm.blui_start_context_action'
    bl_label = 'Start Application Action'
    app_id: StringProperty(options={'SKIP_SAVE'})
    action: EnumProperty(items=(('OPEN', 'Open App', ''), ('PIN', 'Pin or Unpin App', ''),
                                ('LOCATION', 'Open File Location', '')))

    def execute(self, context):
        state = taskbar_windows.menu_state(context.window)
        if self.action == 'OPEN':
            start_menu.launch(self.app_id)
        elif self.action == 'PIN':
            start_menu.pin(self.app_id)
        else:
            start_menu.open_location(self.app_id)
        source = state.get('source')
        taskbar_windows.close_window(context.window)
        if self.action == 'OPEN' and source:
            parent = next((item for item in taskbar_windows.role_windows('STARTMENU')
                           if (item.as_pointer(), item.blui_native_handle) == tuple(source)), None)
            if parent is not None:
                taskbar_windows.close_window(parent)
        return {'FINISHED'}


def draw_context(layout, context, state):
    layout.operator_context = 'EXEC_DEFAULT'
    kind = state.get('kind')
    if kind == 'START_APP':
        identity = state.get('app_id', '')
        value = start_menu.snapshot()
        row = next((row for row in value['rows'] if row['id'] == identity), None)
        if not row:
            layout.label(text=iface('This application changed; refresh the taskbar'), icon='INFO', translate=False)
            return
        layout.label(text=row['name'], translate=False)
        layout.separator()
        for action, label, icon in (('OPEN', 'Open App', 'PLAY'),
                ('PIN', 'Unpin App' if identity in value['pins'] else 'Pin App', 'PINNED'),
                ('LOCATION', 'Open File Location', 'FILE_FOLDER')):
            op = layout.operator('wm.blui_start_context_action', text=iface(label), icon=icon, translate=False)
            op.app_id, op.action = identity, action
        return
    if kind == 'START_CONTEXT':
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator('wm.blui_start_menu', text=iface('Start'), icon='WINDOW', translate=False)
        layout.operator('wm.blui_taskbar_settings', text=iface('Taskbar Settings'), icon='PREFERENCES', translate=False)
        return
    group = taskbar_actions.find_group(state.get('key', ''), monitor=state.get('device', ''))
    if not group:
        layout.label(text=iface('This application changed; refresh the taskbar'), icon='INFO', translate=False)
        return
    layout.label(text=group['title'], translate=False)
    layout.separator()
    for action, label, icon in (('ACTIVATE', 'Activate Window', 'WINDOW'),
            ('MINIMIZE', 'Minimize Window', 'REMOVE'), ('NEW', 'New Application Instance', 'ADD'),
            ('CLOSE', 'Close Window', 'X')):
        row = layout.row()
        row.enabled = any(task.get('actionable') for task in group['tasks'])
        if action == 'NEW':
            row.enabled = any(taskbar_actions.taskbar_groups.can_launch(task) for task in group['tasks'])
        op = row.operator('wm.blui_task_context_action', text=iface(label), icon=icon, translate=False)
        op.key, op.action = group['key'], action


classes = (WM_OT_blui_shell_context_menu, WM_OT_blui_task_context_action, WM_OT_blui_start_context_action)
