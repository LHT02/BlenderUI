# SPDX-License-Identifier: GPL-2.0-or-later
"""Localized explicit enable/restore entries; draw reads only RAM state."""
from bpy.props import EnumProperty
from bpy.types import Operator
from blui_explorer.localization import iface
from . import desktop_service


class WM_OT_blui_windows_desktop(Operator):
    bl_idname = 'wm.blui_windows_desktop'
    bl_label = 'Windows Desktop'
    action: EnumProperty(items=(('ENABLE', 'Use BLUI as Windows Desktop', ''),
                                ('RESTORE', 'Restore Windows Desktop', '')), options={'SKIP_SAVE'})

    def execute(self, _context):
        try:
            desktop_service.enable() if self.action == 'ENABLE' else desktop_service.restore()
        except (RuntimeError, OSError, ValueError, ReferenceError) as exc:
            self.report({'WARNING'}, iface(str(exc)))
            return {'CANCELLED'}
        return {'FINISHED'}


def draw_settings(layout, _context=None):
    state = desktop_service.snapshot()
    column = layout.column(align=True)
    column.label(text=iface('Windows Desktop'), icon='NODETREE', translate=False)
    column.label(text=iface('Desktop replacement is off by default'), icon='INFO', translate=False)
    column.operator('wm.blui_windows_desktop', text=iface('Use BLUI as Windows Desktop'),
                    icon='NODETREE', translate=False).action = 'ENABLE'
    # Restoration is never disabled just because loading, an error or a previous
    # guardian prevents enable; it is the escape hatch, not a boolean toggle.
    column.operator('wm.blui_windows_desktop', text=iface('Restore Windows Desktop'),
                    icon='LOOP_BACK', translate=False).action = 'RESTORE'
    column.label(text=iface(state['state']), translate=False)
    if state.get('error'):
        column.label(text=iface(state['error']), icon='ERROR', translate=False)


classes = (WM_OT_blui_windows_desktop,)
