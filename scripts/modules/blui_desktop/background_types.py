# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit wallpaper loading and native desktop settings UI."""
import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ImportHelper
from blui_explorer.localization import iface
from . import background


def _board(context):
    space = context.space_data
    tree = space.node_tree if space and space.type == 'NODE_EDITOR' else None
    return tree if tree and tree.bl_idname == 'BLUIDesktopTree' else None


class BackgroundAction:
    @classmethod
    def poll(cls, context):
        return _board(context) is not None


def _submit(operator, context, path):
    from . import runtime
    try:
        runtime.submit('background', _board(context), path)
    except (RuntimeError, ValueError, OSError) as error:
        operator.report({'WARNING'}, str(error))
        return {'CANCELLED'}
    return {'FINISHED'}


class WM_OT_blui_background_load(BackgroundAction, Operator, ImportHelper):
    bl_idname = 'wm.blui_background_load'
    bl_label = 'Choose Desktop Background'
    bl_description = 'Decode a PNG or JPEG background in an isolated helper without blocking the desktop'
    filename_ext = '.png'
    filter_glob: StringProperty(default='*.png;*.jpg;*.jpeg', options={'HIDDEN'})

    def execute(self, context):
        return _submit(self, context, self.filepath)


class WM_OT_blui_background_reload(BackgroundAction, Operator):
    bl_idname = 'wm.blui_background_reload'
    bl_label = 'Reload Background'

    def execute(self, context):
        path = _board(context).background_path
        if not path:
            return {'CANCELLED'}
        return _submit(self, context, path)


class WM_OT_blui_background_clear(BackgroundAction, Operator):
    bl_idname = 'wm.blui_background_clear'
    bl_label = 'Remove Background'
    bl_description = 'Remove this desktop background without deleting the source image'
    bl_options = {'UNDO'}

    def execute(self, context):
        tree = _board(context)
        tree.background_generation += 1
        tree.background_enabled = False
        tree.background_path = ''
        background.clear(tree)
        context.area.tag_redraw()
        return {'FINISHED'}


class BLUI_PT_desktop_background(BackgroundAction, Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Desktop'
    bl_label = 'Desktop Background'

    def draw(self, context):
        tree = _board(context)
        layout = self.layout
        row = layout.row(align=True)
        row.operator('wm.blui_background_load', text=iface('Choose Image'), icon='FILE_IMAGE')
        row.operator('wm.blui_background_reload', text='', icon='FILE_REFRESH')
        row.operator('wm.blui_background_clear', text='', icon='X')
        layout.prop(tree, 'background_path', text=iface('Image'))
        layout.prop(tree, 'background_enabled', text=iface('Show Background'))
        column = layout.column()
        column.enabled = tree.background_enabled
        column.prop(tree, 'background_fit', text=iface('Layout'))
        column.prop(tree, 'background_opacity', text=iface('Opacity'), slider=True)
        column.prop(tree, 'background_align_x', text=iface('Horizontal Alignment'), slider=True)
        column.prop(tree, 'background_align_y', text=iface('Vertical Alignment'), slider=True)
        if tree.background_fit == 'SPAN':
            column.prop(tree, 'monitor', text=iface('Display'))
            column.label(text=iface('Spans physical displays'), icon='INFO')
        layout.label(text=iface('Image alpha reveals the canvas'), icon='INFO')


classes = (WM_OT_blui_background_load, WM_OT_blui_background_reload,
           WM_OT_blui_background_clear, BLUI_PT_desktop_background)
