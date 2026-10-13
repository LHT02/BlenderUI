# SPDX-License-Identifier: GPL-2.0-or-later
"""Native taskbar buttons and explicit, identity-checked application actions."""
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator
from . import runtime, taskbar_groups, taskbar_windows
from blui_explorer.localization import iface

_orders = {}


def current_groups(window=None, *, monitor=''):
    monitor = monitor or (taskbar_windows.device(window) if window else '')
    order_key = '*' if taskbar_windows.show_all_tasks() else monitor
    previous = _orders.get(order_key, [])
    values = taskbar_groups.groups(runtime.tasks(), monitor=monitor,
        all_monitors=taskbar_windows.show_all_tasks(), excluded=taskbar_windows.native_handles())
    ranks = {key: index for index, key in enumerate(previous)}
    values.sort(key=lambda group: ranks.get(group['key'], len(ranks)))
    present = {group['key'] for group in values}
    _orders[order_key] = [key for key in previous if key in present] + [group['key'] for group in values if group['key'] not in ranks]
    return values


def find_group(key, window=None, *, monitor=''):
    return next((group for group in current_groups(window, monitor=monitor) if group['key'] == key), None)


def activate(task, *, toggle=False):
    if not task.get('actionable'):
        raise RuntimeError(iface('This task has no verified identity; refresh the taskbar'))
    from . import native_windows
    if not native_windows.act(task['handle'], task['pid'],
            identity=(task['thread_id'], task['process_started'], task['window_class']), toggle=toggle):
        raise RuntimeError(iface('Windows did not allow foreground activation'))
    return True


def launch_group(group):
    task = next((task for task in group['tasks'] if taskbar_groups.can_launch(task)), None)
    if task is None:
        raise ValueError(iface('This application cannot safely start a new instance'))
    runtime.submit('task_launch', None, task)


def chooser(context, *, kind='GROUP', key=''):
    source = context.window
    window = next(iter(taskbar_windows.role_windows('TASK_CHOOSER')), None)
    created = window is None
    group = find_group(key, source) if key else None
    height = min(760, 160 + 42 * (len(group['tasks']) if group else 6))
    if created:
        window = taskbar_windows.create(context, 'TASK_CHOOSER', 440, height)
    try:
        taskbar_windows.set_menu_state(window, {'kind': kind, 'key': key,
                                              'device': taskbar_windows.device(source)})
        taskbar_windows.place_menu(window, source, 440, height)
    except Exception:
        if created:
            taskbar_windows.close_window(window)
        raise
    return window


class WM_OT_blui_taskbar_open(Operator):
    bl_idname = 'wm.blui_taskbar_open'
    bl_label = 'Open BLUI Taskbar'
    bl_description = 'Open an independent native taskbar; Windows taskbar stays visible unless explicitly hidden'
    all_displays: BoolProperty(name='All Displays', default=True)

    def execute(self, context):
        from . import taskbar, session
        if not session.disable_for_tests:
            taskbar.start(session.storage_directory())
        taskbar_windows.open_for_displays(context, all_displays=self.all_displays)
        return {'FINISHED'}


class WM_OT_blui_taskbar_close(Operator):
    bl_idname = 'wm.blui_taskbar_close'
    bl_label = 'Close BLUI Taskbar'
    bl_description = 'Restore the Windows taskbar and close only BLUI shell UI windows'

    def execute(self, context):
        from . import taskbar, session
        if not session.disable_for_tests:
            taskbar.start(session.storage_directory())
            taskbar.request('restore')
        taskbar_windows.close(context)
        return {'FINISHED'}


class WM_OT_blui_taskbar_group(Operator):
    bl_idname = 'wm.blui_taskbar_group'
    bl_label = 'Application'
    key: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        group = find_group(properties.key, context.window)
        return group['title'] + ' · ' + str(len(group['tasks'])) if group else iface('Application')

    def invoke(self, context, event):
        group = find_group(self.key, context.window)
        if not group:
            return {'CANCELLED'}
        if event.shift or event.type == 'MIDDLEMOUSE':
            launch_group(group)
        elif len(group['tasks']) == 1:
            activate(group['tasks'][0], toggle=True)
        else:
            chooser(context, key=self.key)
        return {'FINISHED'}

    def execute(self, context):
        group = find_group(self.key, context.window)
        if not group:
            return {'CANCELLED'}
        if len(group['tasks']) == 1:
            activate(group['tasks'][0], toggle=True)
        else:
            chooser(context, key=self.key)
        return {'FINISHED'}


class WM_OT_blui_taskbar_middle(Operator):
    bl_idname = 'wm.blui_taskbar_middle'
    bl_label = 'New Application Instance'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return bool(context.window and context.window.blui_is_taskbar)

    def invoke(self, context, _event):
        hovered = getattr(context, 'blui_taskbar_button', None)
        if not hovered or hovered.bl_rna.identifier != 'WM_OT_blui_taskbar_group':
            # A static taskbar must not pass empty-space middle clicks to Info's
            # inherited View2D panning handler or reuse a previously clicked app.
            return {'CANCELLED'} if _event.type == 'MIDDLEMOUSE' else {'PASS_THROUGH'}
        group = find_group(hovered.key, context.window)
        if not group:
            return {'CANCELLED'}
        launch_group(group)
        return {'FINISHED'}


class WM_OT_blui_taskbar_pick(Operator):
    bl_idname = 'wm.blui_taskbar_pick'
    bl_label = 'Activate Window'
    key: StringProperty(options={'SKIP_SAVE'})
    handle: StringProperty(options={'SKIP_SAVE'})
    new_instance: BoolProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return bool(context.window and context.window.blui_shell_role == 'TASK_CHOOSER')

    def execute(self, context):
        state = taskbar_windows.menu_state(context.window)
        group = find_group(self.key, monitor=state.get('device', ''))
        if not group:
            return {'CANCELLED'}
        if self.new_instance:
            launch_group(group)
        else:
            task = next((task for task in group['tasks'] if task['handle'] == self.handle), None)
            if not task:
                return {'CANCELLED'}
            activate(task)
        taskbar_windows.close_window(context.window)
        return {'FINISHED'}


class WM_OT_blui_taskbar_settings(Operator):
    bl_idname = 'wm.blui_taskbar_settings'
    bl_label = 'Taskbar Settings'

    def execute(self, context):
        chooser(context, kind='SETTINGS')
        return {'FINISHED'}


class WM_OT_blui_taskbar_layout(Operator):
    bl_idname = 'wm.blui_taskbar_layout'
    bl_label = 'Taskbar Layout'
    mode: EnumProperty(items=(('LEFT', 'Windows 10: Left', ''), ('CENTER', 'Windows 11: Center', ''),
                             ('ALL_DISPLAYS', 'All Displays', ''), ('PRIMARY_DISPLAY', 'Primary Display', ''),
                             ('ALL_TASKS', 'All Application Windows', ''), ('THIS_DISPLAY', 'Windows on This Display', '')))

    def execute(self, context):
        if self.mode in ('LEFT', 'CENTER'):
            taskbar_windows.set_alignment(self.mode)
        elif self.mode in ('ALL_DISPLAYS', 'PRIMARY_DISPLAY'):
            taskbar_windows.open_for_displays(context, all_displays=self.mode == 'ALL_DISPLAYS')
        else:
            taskbar_windows.set_show_all_tasks(self.mode == 'ALL_TASKS')
        return {'FINISHED'}


classes = (WM_OT_blui_taskbar_open, WM_OT_blui_taskbar_close, WM_OT_blui_taskbar_group,
           WM_OT_blui_taskbar_middle, WM_OT_blui_taskbar_pick, WM_OT_blui_taskbar_settings,
           WM_OT_blui_taskbar_layout)


def _guard_invoke(method):
    def invoke(self, context, event):
        try:
            return method(self, context, event)
        except (RuntimeError, OSError, ValueError, ReferenceError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
    return invoke


for _class in classes:
    if hasattr(_class, 'invoke'):
        _class.invoke = _guard_invoke(_class.invoke)
