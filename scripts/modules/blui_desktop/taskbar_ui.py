# SPDX-License-Identifier: GPL-2.0-or-later
"""User-requested system taskbar visibility switch; recovery always remains available."""
from bpy.props import EnumProperty
from bpy.types import Operator
from . import taskbar, session
from blui_explorer.localization import iface


class WM_OT_blui_windows_taskbar(Operator):
    bl_idname = 'wm.blui_windows_taskbar'
    bl_label = 'Windows Taskbar'
    action: EnumProperty(items=(('hide', 'Hide Windows Taskbar', ''), ('restore', 'Restore Windows Taskbar', '')))

    def execute(self, context):
        try:
            if self.action == 'hide':
                from . import taskbar_windows
                if not taskbar_windows.open_for_displays(context, all_displays=taskbar_windows.all_displays()):
                    self.report({'INFO'}, iface('Loading...'))
                    return {'CANCELLED'}
            taskbar.start(session.storage_directory())
            taskbar.request(self.action)
        except (RuntimeError, ValueError, OSError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


from .taskbar_actions import classes as action_classes
from .taskbar_draw import classes as draw_classes

classes = (WM_OT_blui_windows_taskbar,) + action_classes + draw_classes
