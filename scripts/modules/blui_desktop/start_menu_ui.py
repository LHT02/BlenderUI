# SPDX-License-Identifier: GPL-2.0-or-later
"""Native Start-menu panel, shared by the independent menu window and popup fallback."""
import bpy
from bpy.props import EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Menu, Operator, Panel, PropertyGroup
from blui_explorer.localization import iface
from . import icon_cache, session, start_menu, start_menu_model as schema

PAGE_SIZE = 15
WIDTH, HEIGHT = 600, 680
_focused = set()


def _filter_changed(settings, _context):
    settings.page = 0


class BLUI_StartMenuSettings(PropertyGroup):
    query: StringProperty(name='Search Apps', maxlen=256, update=_filter_changed, options={'SKIP_SAVE'})
    section: EnumProperty(name='Programs', default='ALL', options={'SKIP_SAVE'}, update=_filter_changed,
        items=(('PINNED', 'Pinned Apps', ''), ('ALL', 'All Apps', ''), ('RECENT', 'Recently Opened Apps', '')))
    page: IntProperty(default=0, min=0, max=68, options={'SKIP_SAVE'})


def register_props():
    bpy.types.WindowManager.blui_start_menu_settings = PointerProperty(type=BLUI_StartMenuSettings, options={'SKIP_SAVE'})


def unregister_props():
    if bpy.app.timers.is_registered(_focus_tick):
        bpy.app.timers.unregister(_focus_tick)
    _focused.clear()
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
    windows = [window for window in bpy.context.window_manager.windows if _role(window) == 'STARTMENU']
    if not windows:
        _focused.clear()
        return None
    # Native text/menu/property confirmations own modal state; do not invalidate their RNA.
    if runtime.interaction_busy(None):
        return .2
    live = set()
    for window in windows:
        token = (window.as_pointer(), window.blui_native_handle)
        live.add(token)
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


def _app_button(layout, row):
    icon = icon_cache.value(row['path'])
    kwargs = {'icon_value': icon} if icon else {'icon': 'WINDOW'}
    op = layout.operator('wm.blui_start_launch', text=row['name'], translate=False, **kwargs)
    op.app_id = row['id']


def draw_menu(layout, context):
    settings, value = context.window_manager.blui_start_menu_settings, start_menu.snapshot()
    layout.use_property_split = False
    layout.use_property_decorate = False
    heading = layout.row(align=True)
    heading.label(text=iface('Start'), icon='WINDOW', translate=False)
    heading.operator('wm.blui_start_refresh', text='', icon='FILE_REFRESH')
    if _role(context.window) == 'STARTMENU':
        heading.operator('wm.window_close', text='', icon='X').force_close = True
    layout.prop(settings, 'query', text='', icon='VIEWZOOM')
    layout.prop(settings, 'section', expand=True)
    if value['loading']:
        layout.label(text=iface('Loading Apps'), icon='TIME', translate=False)
    if value['error']:
        box = layout.box()
        box.label(text=value['error'][:100], icon='ERROR', translate=False)
    if value['truncated']:
        layout.label(text=iface('App list limited; refresh to update'), icon='INFO', translate=False)
    rows = _rows(settings, value)
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(settings.page, pages - 1)
    current = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    if not current and value['loaded']:
        layout.label(text=iface('No Matching Apps'), icon='INFO', translate=False)
    if settings.section == 'PINNED' and value['pins'] and not settings.query.strip():
        grid = layout.grid_flow(columns=3, even_columns=True, align=True)
        for row in current:
            cell = grid.column(align=True)
            _app_button(cell, row)
            cell.operator('wm.blui_start_pin', text=iface('Unpin App'), icon='UNPINNED', translate=False).app_id = row['id']
    else:
        for row in current:
            line = layout.row(align=True)
            _app_button(line, row)
            pinned = row['id'] in value['pins']
            op = line.operator('wm.blui_start_pin', text='', icon='PINNED' if pinned else 'UNPINNED', depress=pinned)
            op.app_id = row['id']
    if pages > 1:
        pager = layout.row(align=True)
        prev = pager.row()
        prev.enabled = page > 0
        prev.operator('wm.blui_start_page', text='', icon='TRIA_LEFT').page = max(0, page - 1)
        pager.label(text=f'{page + 1} / {pages}', translate=False)
        next_page = pager.row()
        next_page.enabled = page + 1 < pages
        next_page.operator('wm.blui_start_page', text='', icon='TRIA_RIGHT').page = page + 1
    layout.separator()
    system = layout.row(align=True)
    system.operator('wm.blui_start_system', text=iface('Files'), icon='FILE_FOLDER', translate=False).action = 'FILES'
    system.operator('wm.blui_start_system', text=iface('Windows Settings'), icon='PREFERENCES', translate=False).action = 'SETTINGS'
    system.menu('BLUI_MT_start_power', text=iface('Power'), icon='QUIT', translate=False)


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
        settings.section = 'PINNED' if start_menu.snapshot()['pins'] else 'ALL'
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
        # Useful for older developer binaries; release taskbars always use the full independent window.
        return context.window_manager.invoke_props_dialog(self, width=WIDTH)

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
        return _role(context.window) in {'STARTMENU', 'TASK_CHOOSER'}

    def execute(self, context):
        if _role(context.window) not in {'STARTMENU', 'TASK_CHOOSER'}:
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


class WM_OT_blui_start_page(Operator):
    bl_idname = 'wm.blui_start_page'
    bl_label = 'App Page'
    page: IntProperty(min=0, max=68, options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        context.window_manager.blui_start_menu_settings.page = self.page
        _redraw_menus(context)
        return {'FINISHED'}


class WM_OT_blui_start_system(Operator):
    bl_idname = 'wm.blui_start_system'
    bl_label = 'Start Menu System Action'
    action: EnumProperty(items=tuple((key, label, '') for key, label in
        (('FILES', 'Files'), ('SETTINGS', 'Windows Settings'), ('POWER_SETTINGS', 'Power Settings'),
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


classes = (BLUI_StartMenuSettings, WM_OT_blui_start_menu, WM_OT_blui_start_refresh,
           WM_OT_blui_start_launch, WM_OT_blui_start_pin, WM_OT_blui_start_page,
           WM_OT_blui_start_system, WM_OT_blui_shell_popup_close, BLUI_MT_start_power, BLUI_PT_start_menu)
