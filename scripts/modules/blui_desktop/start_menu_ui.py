# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent, Open-Shell/Windows 7 style two-column native Start menu."""
import os
import bpy
from bpy.props import EnumProperty, PointerProperty, StringProperty
from bpy.types import Menu, Operator, Panel
from blui_explorer.localization import iface
from . import session, start_menu, start_menu_contents as contents, start_menu_layout, start_menu_model as schema
from .start_menu_contents import BLUI_StartMenuSettings

WIDTH, HEIGHT = 640, 620
_focused = set()
_username = os.environ.get('USERNAME', '')[:80]


def register_props():
    contents.reset()
    bpy.types.WindowManager.blui_start_menu_settings = PointerProperty(type=BLUI_StartMenuSettings, options={'SKIP_SAVE'})


def unregister_props():
    if bpy.app.timers.is_registered(_focus_tick):
        bpy.app.timers.unregister(_focus_tick)
    _focused.clear()
    contents.reset()
    if hasattr(bpy.types.WindowManager, 'blui_start_menu_settings'):
        del bpy.types.WindowManager.blui_start_menu_settings


def _role(window):
    return getattr(window, 'blui_shell_role', '') if window else ''


def _shell_windows_available():
    # Internal native operators need not be exposed as classes in bpy.types.
    # bpy.ops itself accepts arbitrary attribute names, so use real RNA lookup.
    try:
        bpy.ops.wm.blui_shell_window_create.get_rna_type()
    except (RuntimeError, AttributeError):
        return False
    return True


def _close_menu(context):
    if _role(context.window) == 'STARTMENU':
        bpy.ops.wm.window_close(force_close=True)


def _redraw_menus(context):
    for window in context.window_manager.windows:
        if _role(window) == 'STARTMENU':
            for area in window.screen.areas:
                area.tag_redraw()


def _focus_tick():
    """Fresh role lookups only; never retain a Window or close a normal user window."""
    from . import runtime, taskbar_windows
    all_windows = list(bpy.context.window_manager.windows)
    windows = [window for window in all_windows if _role(window) == 'STARTMENU']
    if not windows:
        _focused.clear()
        return None
    # Native text/menu/property confirmations own modal state; do not invalidate their RNA.
    if runtime.shell_interaction_busy():
        return .2
    if contents.sync(bpy.context.window_manager.blui_start_menu_settings, start_menu.snapshot()):
        _redraw_menus(bpy.context)
    live = set()
    for window in windows:
        token = (window.as_pointer(), window.blui_native_handle)
        live.add(token)
        if start_menu_layout.owns_context_child(token, all_windows, taskbar_windows.menu_state):
            # Right-click actions have their own full-height HWND. Moving focus
            # from Start to its child is not a request to close the parent menu.
            _focused.add(token)
            continue
        try:
            if taskbar_windows.is_foreground(window):
                _focused.add(token)
            elif token in _focused:
                with bpy.context.temp_override(window=window):
                    if _role(window) == 'STARTMENU':
                        bpy.ops.wm.window_close(force_close=True)
                _focused.discard(token)
        except (RuntimeError, OSError, ValueError, ReferenceError):
            # A refused foreground query is not permission to close a window.
            pass
    _focused.intersection_update(live)
    return .2


def _rows(settings, value):
    if settings.query.strip():
        return schema.search(value['rows'], settings.query)
    if settings.section == 'RECENT':
        return schema.selected(value['rows'], value['recent'])
    if settings.section == 'PINNED':
        return schema.selected(value['rows'], value['pins'])
    return value['rows']


def _system_button(layout, action, label, icon, *, scale=1.5):
    row = layout.row()
    row.scale_y = scale
    row.alignment = 'EXPAND'
    row.operator('wm.blui_start_system', text=iface(label), icon=icon,
                 emboss=False, translate=False).action = action


def draw_menu(layout, context):
    settings, value = context.window_manager.blui_start_menu_settings, start_menu.snapshot()
    layout.use_property_split = False
    layout.use_property_decorate = False
    layout.operator_context = 'INVOKE_DEFAULT'
    dimensions = start_menu_layout.metrics(context.region.height, context.preferences.system.ui_scale,
        empty=not settings.items and value['loaded'])
    columns = layout.split(factor=.64)
    left = columns.column(align=True)
    heading = left.row(align=True)
    caption = 'Search Results' if settings.query.strip() else 'All Programs' if settings.section == 'ALL' else 'Start'
    heading.label(text=iface(caption), translate=False)
    if value['loading']:
        heading.label(text='', icon='TIME')
    if value['error']:
        heading.label(text='', icon='ERROR')
    if not settings.items and value['loaded']:
        left.label(text=iface('No Matching Apps'), icon='INFO', translate=False)
    # UIList consumes wheel events itself. The right system column and bottom
    # search field do not move or change DPI when the application list scrolls.
    left.template_list('BLUI_UL_start_programs', 'start_programs', settings, 'items',
                       settings, 'active', rows=dimensions['rows'], maxrows=dimensions['rows'])
    left.separator(factor=.6)
    programs = left.row()
    programs.scale_y = 1.3
    programs.alignment = 'EXPAND'
    if settings.section == 'ALL' or settings.query.strip():
        programs.operator('wm.blui_start_view', text=iface('Back'), icon='TRIA_LEFT',
                          emboss=False, translate=False).section = 'HOME'
    else:
        programs.operator('wm.blui_start_view', text=iface('All Programs'), icon='TRIA_RIGHT',
                          emboss=False, translate=False).section = 'ALL'
    left.separator(factor=.6)
    left.prop(settings, 'query', text='', icon='VIEWZOOM')
    left.label(text=iface('Search Programs'), translate=False)

    right = columns.column().box().column(align=True)
    user = right.row()
    user.scale_y = dimensions['user_scale']
    user.alignment = 'LEFT'
    user.label(text=_username or iface('User'), icon='USER', translate=False)
    right.separator(factor=dimensions['separator'])
    for action, label, icon in (
            ('FILES', 'User Files', 'FILE_FOLDER'), ('DOCUMENTS', 'Documents', 'FILE'),
            ('PICTURES', 'Pictures', 'IMAGE_DATA'), ('MUSIC', 'Music', 'SOUND'),
            ('DOWNLOADS', 'Downloads', 'IMPORT'), ('COMPUTER', 'Computer', 'DESKTOP')):
        if action not in dimensions['hidden']:
            _system_button(right, action, label, icon, scale=dimensions['row_scale'])
    if dimensions['hidden']:
        places = right.row()
        places.scale_y = dimensions['row_scale']
        places.menu('BLUI_MT_start_locations', text=iface('More Places'), icon='FILE_FOLDER', translate=False)
    right.separator(factor=dimensions['separator'])
    if 'CONTROL_PANEL' not in dimensions['hidden']:
        _system_button(right, 'CONTROL_PANEL', 'Control Panel', 'PREFERENCES', scale=dimensions['row_scale'])
    _system_button(right, 'SETTINGS', 'Windows Settings', 'PREFERENCES', scale=dimensions['row_scale'])
    refresh = right.row()
    refresh.scale_y = dimensions['row_scale']
    refresh.alignment = 'EXPAND'
    refresh.operator('wm.blui_start_refresh', text=iface('Refresh Apps'), icon='FILE_REFRESH',
                     emboss=False, translate=False)
    # Both columns remain fixed; only the native list above owns scrolling.
    if dimensions['spacer_units']:
        spacer = right.column()
        spacer.ui_units_y = dimensions['spacer_units']
        spacer.label(text='')
    power = right.row(align=True)
    power.scale_y = 1.3
    power.operator('wm.blui_start_system', text=iface('Shut Down'), icon='QUIT', translate=False).action = 'SHUTDOWN'
    power.menu('BLUI_MT_start_power', text='', icon='TRIA_DOWN')


class WM_OT_blui_start_menu(Operator):
    bl_idname = 'wm.blui_start_menu'
    bl_label = 'Start'
    bl_description = 'Open indexed Programs, pinned apps, recent apps and local app search'

    def draw(self, context):
        draw_menu(self.layout, context)

    def invoke(self, context, _event):
        start_menu.ensure(session.storage_directory())
        settings = context.window_manager.blui_start_menu_settings
        settings.query = ''
        settings.section = 'HOME'
        settings.expanded_folders = ''
        contents.sync(settings, start_menu.snapshot())
        if _shell_windows_available():
            source = context.window
            window = next((window for window in context.window_manager.windows if _role(window) == 'STARTMENU'), None)
            if window is not None and _role(source) == 'TASKBAR':
                with context.temp_override(window=window):
                    _close_menu(bpy.context)
                return {'FINISHED'}
            if window is None:
                before = {window.as_pointer() for window in context.window_manager.windows}
                result = bpy.ops.wm.blui_shell_window_create(role='STARTMENU', width=WIDTH, height=HEIGHT)
                window = next((window for window in context.window_manager.windows
                               if window.as_pointer() not in before and _role(window) == 'STARTMENU'), None)
                if result != {'FINISHED'} or window is None:
                    raise RuntimeError(iface('Could not open Start menu'))
            from . import taskbar_windows
            taskbar_windows.place_menu(window, source, WIDTH, HEIGHT)
            if not bpy.app.timers.is_registered(_focus_tick):
                bpy.app.timers.register(_focus_tick, first_interval=.3)
            _redraw_menus(context)
            return {'FINISHED'}
        # A dialog in a 56px taskbar is clipped by its HWND and cannot be a Start menu.
        self.report({'ERROR'}, iface('Could not open Start menu'))
        return {'CANCELLED'}

    def execute(self, _context):
        return {'FINISHED'}


class WM_OT_blui_start_refresh(Operator):
    bl_idname = 'wm.blui_start_refresh'
    bl_label = 'Refresh Apps'

    def execute(self, _context):
        start_menu.ensure(session.storage_directory(), refresh=True)
        return {'FINISHED'}


class WM_OT_blui_shell_popup_close(Operator):
    bl_idname = 'wm.blui_shell_popup_close'
    bl_label = 'Close Shell Popup'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _role(context.window) in {'STARTMENU', 'TASK_CHOOSER', 'TASK_PREVIEW'}

    def execute(self, context):
        if _role(context.window) not in {'STARTMENU', 'TASK_CHOOSER', 'TASK_PREVIEW'}:
            return {'CANCELLED'}
        bpy.ops.wm.window_close(force_close=True)
        return {'FINISHED'}


class WM_OT_blui_start_launch(Operator):
    bl_idname = 'wm.blui_start_launch'
    bl_label = 'Open App'
    app_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        start_menu.launch(self.app_id)
        _close_menu(context)
        return {'FINISHED'}


class WM_OT_blui_start_pin(Operator):
    bl_idname = 'wm.blui_start_pin'
    bl_label = 'Pin or Unpin App'
    app_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        start_menu.pin(self.app_id)
        _redraw_menus(context)
        return {'FINISHED'}


class WM_OT_blui_start_location(Operator):
    bl_idname = 'wm.blui_start_location'
    bl_label = 'Open File Location'
    app_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        start_menu.open_location(self.app_id)
        _redraw_menus(context)
        return {'FINISHED'}


class WM_OT_blui_start_system(Operator):
    bl_idname = 'wm.blui_start_system'
    bl_label = 'Start Menu System Action'
    action: EnumProperty(items=tuple((key, label, '') for key, label in
        (('FILES', 'User Files'), ('DOCUMENTS', 'Documents'), ('PICTURES', 'Pictures'),
         ('MUSIC', 'Music'), ('DOWNLOADS', 'Downloads'), ('COMPUTER', 'Computer'),
         ('CONTROL_PANEL', 'Control Panel'), ('SETTINGS', 'Windows Settings'), ('POWER_SETTINGS', 'Power Settings'),
         ('LOCK', 'Lock Windows'), ('SHUTDOWN', 'Shut Down Windows'), ('RESTART', 'Restart Windows'))))

    def invoke(self, context, _event):
        if self.action in {'LOCK', 'SHUTDOWN', 'RESTART'}:
            return context.window_manager.invoke_props_dialog(self, width=440)
        return self.execute(context)

    def draw(self, _context):
        label = {'LOCK': 'Lock Windows?', 'SHUTDOWN': 'Shut Down Windows?',
                 'RESTART': 'Restart Windows?'}.get(self.action, 'Continue?')
        self.layout.label(text=iface(label), icon='QUESTION', translate=False)
        if self.action in {'SHUTDOWN', 'RESTART'}:
            self.layout.label(text=iface('Save your work before continuing'), translate=False)

    def execute(self, context):
        start_menu.system_action(self.action)
        _close_menu(context)
        return {'FINISHED'}


class BLUI_MT_start_power(Menu):
    bl_label = 'Power'

    def draw(self, _context):
        self.layout.operator_context = 'INVOKE_DEFAULT'
        for action, label, icon in (('POWER_SETTINGS', 'Power Settings', 'PREFERENCES'),
                                    ('LOCK', 'Lock Windows', 'LOCKED'),
                                    ('SHUTDOWN', 'Shut Down Windows', 'QUIT'),
                                    ('RESTART', 'Restart Windows', 'FILE_REFRESH')):
            self.layout.operator('wm.blui_start_system', text=iface(label), icon=icon, translate=False).action = action


class BLUI_MT_start_locations(Menu):
    bl_label = 'More Places'

    def draw(self, _context):
        self.layout.operator_context = 'INVOKE_DEFAULT'
        for action, label, icon in (('DOCUMENTS', 'Documents', 'FILE'),
                ('PICTURES', 'Pictures', 'IMAGE_DATA'), ('MUSIC', 'Music', 'SOUND'),
                ('DOWNLOADS', 'Downloads', 'IMPORT'), ('CONTROL_PANEL', 'Control Panel', 'PREFERENCES')):
            self.layout.operator('wm.blui_start_system', text=iface(label), icon=icon, translate=False).action = action


class BLUI_PT_start_menu(Panel):
    bl_space_type = 'INFO'
    bl_region_type = 'WINDOW'
    bl_label = 'Start'
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        return _role(context.window) == 'STARTMENU'

    def draw(self, context):
        draw_menu(self.layout, context)


classes = contents.classes + (WM_OT_blui_start_menu, WM_OT_blui_start_refresh,
           WM_OT_blui_start_launch, WM_OT_blui_start_pin, WM_OT_blui_start_location,
           WM_OT_blui_start_system, WM_OT_blui_shell_popup_close, BLUI_MT_start_power,
           BLUI_MT_start_locations, BLUI_PT_start_menu)
