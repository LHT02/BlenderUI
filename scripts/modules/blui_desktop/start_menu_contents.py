# SPDX-License-Identifier: GPL-2.0-or-later
"""RNA list adapter for the independently scrolling, two-column Start menu."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList
from blui_explorer.localization import iface
from . import icon_cache, start_menu, start_menu_model as schema, start_menu_tree

LIST_ROWS = 21
_fingerprint = None
_index_rows = None


def _filter_changed(settings, _context):
    settings.active = -1
    # Native RNA updates run at an event boundary, not inside a draw callback.
    # Search results should change while typing, not only after leaving the field.
    sync(settings, start_menu.snapshot())


class BLUI_StartMenuItem(PropertyGroup):
    kind: StringProperty(options={'SKIP_SAVE'})
    name: StringProperty(options={'SKIP_SAVE'})
    app_id: StringProperty(options={'SKIP_SAVE'})
    path: StringProperty(options={'SKIP_SAVE'})
    folder_id: StringProperty(options={'SKIP_SAVE'})
    depth: IntProperty(options={'SKIP_SAVE'})
    expanded: BoolProperty(options={'SKIP_SAVE'})


class BLUI_StartMenuSettings(PropertyGroup):
    query: StringProperty(name='Search Apps', maxlen=256, update=_filter_changed, options={'SKIP_SAVE'})
    section: EnumProperty(name='Programs', default='HOME', options={'SKIP_SAVE'}, update=_filter_changed,
        items=(('HOME', 'Start', ''), ('ALL', 'All Programs', ''),
               ('PINNED', 'Pinned Apps', ''), ('RECENT', 'Recently Opened Apps', '')))
    expanded_folders: StringProperty(default='', options={'SKIP_SAVE'})
    items: CollectionProperty(type=BLUI_StartMenuItem, options={'SKIP_SAVE'})
    active: IntProperty(default=-1, min=-1, options={'SKIP_SAVE'})


def sync(settings, value):
    """Update transient RNA outside draw callbacks; only memory is queried."""
    global _fingerprint, _index_rows
    fingerprint = (settings.as_pointer(), id(value['rows']), value['revision'], settings.query,
                   settings.section, settings.expanded_folders)
    if fingerprint == _fingerprint:
        return False
    opened = settings.expanded_folders.split() if settings.expanded_folders else ()
    rows = start_menu_tree.contents(value, settings.section, settings.query, opened)
    settings.items.clear()
    for row in rows:
        item = settings.items.add()
        for name, item_value in row.items():
            setattr(item, name, item_value)
    settings.active = -1
    _fingerprint = fingerprint
    _index_rows = value['rows']  # Keep the list alive so its cached id cannot be recycled.
    return True


def reset():
    global _fingerprint, _index_rows
    _fingerprint = None
    _index_rows = None


class BLUI_UL_start_programs(UIList):
    """Standard list scrolling is deliberately separate from the menu's right column."""
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname):
        layout.operator_context = 'EXEC_DEFAULT'
        row = layout.row(align=True)
        row.alignment = 'EXPAND'
        if item.depth:
            spacer = row.row()
            spacer.ui_units_x = min(item.depth, 12) * .7
            spacer.label(text='')
        if item.kind == 'HEADER':
            row.label(text=iface(item.name), translate=False)
        elif item.kind == 'FOLDER':
            row.operator('wm.blui_start_folder', text='', emboss=False,
                         icon='DISCLOSURE_TRI_DOWN' if item.expanded else 'DISCLOSURE_TRI_RIGHT').folder_id = item.folder_id
            op = row.operator('wm.blui_start_folder', text=item.name, icon='FILE_FOLDER',
                              emboss=False, translate=False)
            op.folder_id = item.folder_id
        else:
            icon = icon_cache.value(item.path)
            kwargs = {'icon_value': icon} if icon else {'icon': 'WINDOW'}
            op = row.operator('wm.blui_start_launch', text=item.name, emboss=False, translate=False, **kwargs)
            op.app_id = item.app_id

    def draw_filter(self, _context, _layout):
        # The persistent search box belongs at the bottom, like Open-Shell's Win7 menu.
        pass


class WM_OT_blui_start_folder(Operator):
    bl_idname = 'wm.blui_start_folder'
    bl_label = 'Expand Program Folder'
    folder_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        identity = schema.key(self.folder_id)
        settings = context.window_manager.blui_start_menu_settings
        # Only a currently displayed, indexed Programs folder can be expanded.
        if not any(item.kind == 'FOLDER' and item.folder_id == identity for item in settings.items):
            return {'CANCELLED'}
        expanded = set(settings.expanded_folders.split())
        if identity in expanded:
            expanded.remove(identity)
        else:
            expanded.add(identity)
        settings.expanded_folders = ' '.join(sorted(expanded))
        sync(settings, start_menu.snapshot())
        for area in context.window.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


class WM_OT_blui_start_view(Operator):
    bl_idname = 'wm.blui_start_view'
    bl_label = 'Start Menu View'
    section: EnumProperty(items=(('HOME', 'Start', ''), ('ALL', 'All Programs', '')),
                          options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        settings = context.window_manager.blui_start_menu_settings
        settings.query = ''
        settings.section = self.section
        sync(settings, start_menu.snapshot())
        for area in context.window.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


classes = (BLUI_StartMenuItem, BLUI_StartMenuSettings, BLUI_UL_start_programs,
           WM_OT_blui_start_folder, WM_OT_blui_start_view)
