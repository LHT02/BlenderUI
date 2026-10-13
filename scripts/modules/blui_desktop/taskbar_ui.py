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

    def execute(self, _context):
        try:
            taskbar.start(session.storage_directory())
            taskbar.request(self.action)
        except (RuntimeError, ValueError, OSError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (WM_OT_blui_windows_taskbar,)
