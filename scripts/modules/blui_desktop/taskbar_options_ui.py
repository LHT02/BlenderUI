# SPDX-License-Identifier: GPL-2.0-or-later
"""Native taskbar appearance controls; callbacks only mutate in-memory preferences.

The independent settings window owns these controls. Persistence is serviced by
taskbar_settings.service_tick in the shared runtime, never a draw/RNA callback.
"""
import bpy
from bpy.props import IntProperty, PointerProperty
from bpy.types import Operator, PropertyGroup
from blui_explorer.localization import iface
from . import taskbar_settings

_syncing = False


def values(_context=None):
    value = taskbar_settings.values()
    return {'height': value['height'], 'icon_size': value['icon_size']}


def sync(context=None):
    """Mirror async-loaded or canonicalized values without recursive update writes."""
    global _syncing
    context = context or bpy.context
    wm = getattr(context, 'window_manager', None)
    props = getattr(wm, 'blui_taskbar_options', None) if wm else None
    if props is None:
        return False
    current = values()
    changed = props.height != current['height'] or props.icon_size != current['icon_size']
    previous, _syncing = _syncing, True
    try:
        if props.height != current['height']:
            props.height = current['height']
        if props.icon_size != current['icon_size']:
            props.icon_size = current['icon_size']
    finally:
        _syncing = previous
    return changed


def _changed(context, **kwargs):
    if _syncing:
        return
    taskbar_settings.configure(**kwargs)
    sync(context)
    wm = getattr(context, 'window_manager', None)
    if wm:
        for window in wm.windows:
            if getattr(window, 'blui_shell_role', 'NORMAL') != 'NORMAL':
                for area in window.screen.areas:
                    area.tag_redraw()


def _height_changed(props, context):
    _changed(context, height=props.height)


def _icon_changed(props, context):
    _changed(context, icon_size=props.icon_size)


class BLUI_TaskbarOptions(PropertyGroup):
    height: IntProperty(name='Taskbar Height', default=56,
        min=taskbar_settings.HEIGHT_MIN, max=taskbar_settings.HEIGHT_MAX,
        description='Logical pixels; scaled for each display', update=_height_changed, options={'SKIP_SAVE'})
    icon_size: IntProperty(name='Icon Size', default=32,
        min=taskbar_settings.ICON_MIN, max=taskbar_settings.ICON_MAX,
        description='Logical pixels; scaled for each display', update=_icon_changed, options={'SKIP_SAVE'})


class WM_OT_blui_taskbar_appearance_reset(Operator):
    bl_idname = 'wm.blui_taskbar_appearance_reset'
    bl_label = 'Reset Taskbar Appearance'

    def execute(self, context):
        defaults = taskbar_settings.defaults()
        _changed(context, height=defaults['height'], icon_size=defaults['icon_size'])
        return {'FINISHED'}


def draw_settings(layout, context):
    """Insert into an independent shell settings panel, never the thin taskbar HWND."""
    props = context.window_manager.blui_taskbar_options
    column = layout.column(align=True)
    column.label(text=iface('Taskbar Appearance'), translate=False)
    column.prop(props, 'height', text=iface('Taskbar Height'), slider=True)
    column.prop(props, 'icon_size', text=iface('Icon Size'), slider=True)
    column.label(text=iface('Logical pixels; scaled for each display'), icon='INFO', translate=False)
    column.operator('wm.blui_taskbar_appearance_reset', text=iface('Reset Taskbar Appearance'), translate=False)
    column.label(text=iface('Start stays separate from application groups'), translate=False)
    error = taskbar_settings.error()
    if error:
        column.label(text=iface('Taskbar settings could not be saved'), icon='ERROR', translate=False)


def register_props():
    bpy.types.WindowManager.blui_taskbar_options = PointerProperty(type=BLUI_TaskbarOptions,
                                                                  options={'SKIP_SAVE'})
    sync()


def unregister_props():
    if hasattr(bpy.types.WindowManager, 'blui_taskbar_options'):
        del bpy.types.WindowManager.blui_taskbar_options


classes = (BLUI_TaskbarOptions, WM_OT_blui_taskbar_appearance_reset)
