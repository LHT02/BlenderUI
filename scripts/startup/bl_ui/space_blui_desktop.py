# SPDX-License-Identifier: GPL-2.0-or-later
"""Native node header/sidebar and footer taskbar; no draw-time filesystem or OS queries."""
from bpy.types import Header, Menu, Panel
from bl_ui.space_toolsystem_common import ToolSelectPanelHelper, ToolDef
from blui_desktop import runtime, groups, widgets, session
from blui_desktop.types import canvas, classes as node_classes
from blui_explorer.localization import iface


def _task_button(layout, task, *, minimize=False, text=None):
    row = layout.row(align=True)
    row.enabled = task.get('actionable', False)
    op = row.operator('wm.blui_task_activate', text=text if text is not None else task['title'][:36],
                      icon='WINDOW' if not minimize else 'REMOVE', depress=task['active'], translate=False)
    op.handle, op.pid = task['handle'], task['pid']
    op.thread_id, op.process_started, op.window_class = task['thread_id'], task['process_started'], task['window_class']
    op.minimize = minimize


class BLUI_HT_canvas(Header):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        layout.template_header()
        tree = canvas(context)
        if not tree:
            layout.operator('wm.blui_canvas_initialize', text=iface('Create Canvas'), icon='ADD', translate=False)
            return
        layout.menu('BLUI_MT_canvas_context', text=iface('Canvas'), translate=False)
        layout.menu('BLUI_MT_displays', text=iface('Displays'), translate=False)
        layout.prop(tree, 'directory', text='')
        layout.operator('wm.blui_canvas_refresh', text='', icon='FILE_REFRESH')
        layout.operator('wm.blui_canvas_import', text=iface('Add Files'), icon='ADD', translate=False)
        layout.operator('node.view_all', text='', icon='VIEWZOOM')
        layout.separator_spacer()
        layout.label(text=tree.service_status, translate=False)


class BLUI_HT_taskbar(Header):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'FOOTER'

    def draw(self, context):
        layout = self.layout
        layout.menu('BLUI_MT_desktop_start', text='BLUI', icon='BLENDER')
        layout.separator()
        for task in runtime.tasks()[:6]:
            _task_button(layout, task, text=task['title'][:22])
        layout.menu('BLUI_MT_desktop_tasks', text=iface('All Tasks'), icon='WINDOW', translate=False)
        layout.separator_spacer()
        from bl_operators.blui_file import task_status
        layout.label(text=task_status(), translate=False)
        layout.label(text=iface('MMB: Pan · Wheel: Zoom · Drag: Arrange'), translate=False)
        layout.template_reports_banner()
        layout.template_running_jobs()
        from datetime import datetime
        layout.label(text=datetime.now().strftime('%H:%M'), translate=False)
        if not context.preferences.edit.use_global_undo:
            layout.prop(context.preferences.edit, 'use_global_undo', text=iface('Enable Canvas Undo'))


class BLUI_MT_desktop_start(Menu):
    bl_label = 'BLUI'

    def draw(self, _context):
        layout = self.layout
        layout.operator('wm.blui_desktop_open', text=iface('Desktop Canvas'), icon='NODETREE', translate=False)
        layout.menu('BLUI_MT_displays', text=iface('Displays'), translate=False)
        layout.menu('BLUI_MT_desktop_widgets', text=iface('Widgets'), translate=False)
        layout.separator()
        for action, label in (('hide', 'Hide Windows Taskbar'), ('restore', 'Restore Windows Taskbar')):
            op = layout.operator('wm.blui_windows_taskbar', text=iface(label), translate=False)
            op.action = action
        layout.separator()
        for name, icon in (('Files', 'FILEBROWSER'), ('Images', 'IMAGE'), ('Text', 'TEXT'),
                           ('Video', 'SEQUENCE'), ('Settings', 'PREFERENCES'), ('Console', 'CONSOLE')):
            op = layout.operator('wm.window_new', text=iface(name), icon=icon, translate=False)
            op.workspace = name


class BLUI_MT_desktop_tasks(Menu):
    bl_label = 'All Tasks'

    def draw(self, _context):
        if runtime.task_error():
            self.layout.label(text=runtime.task_error(), icon='ERROR', translate=False)
        if not runtime.tasks():
            self.layout.label(text=iface('Loading...'), translate=False)
        for task in runtime.tasks():
            row = self.layout.row(align=True)
            _task_button(row, task)
            _task_button(row, task, minimize=True, text='')


class BLUI_MT_canvas_context(Menu):
    bl_label = 'Canvas'

    def draw(self, context):
        layout = self.layout
        if not canvas(context):
            layout.operator('wm.blui_canvas_initialize')
            return
        layout.operator('wm.blui_canvas_import')
        layout.operator('wm.blui_canvas_note')
        layout.menu('BLUI_MT_desktop_widgets', text=iface('Widgets'), translate=False)
        layout.operator('wm.blui_background_load', text=iface('Choose Desktop Background'), icon='FILE_IMAGE', translate=False)
        op = layout.operator('node.add_node', text=iface('Add Icon Panel'), icon='NODE_SEL', translate=False)
        op.type, op.use_transform = 'NodeFrame', True
        layout.operator('node.group_make', text=iface('Group Icons'), icon='NODETREE', translate=False)
        layout.operator('node.group_edit', text=iface('Enter Group'), translate=False)
        layout.operator('node.group_ungroup', text=iface('Ungroup Icons'), translate=False)
        layout.separator()
        layout.operator('wm.blui_canvas_open_active', text=iface('Open'), icon='FILE_FOLDER', translate=False)
        for action, label, icon in (('CUT', 'Cut', 'SCISSORS'), ('COPY', 'Copy', 'COPYDOWN'),
                                    ('PASTE', 'Paste', 'PASTEDOWN'), ('RENAME', 'Rename', 'GREASEPENCIL'),
                                    ('RECYCLE', 'Delete to Recycle Bin', 'TRASH')):
            op = layout.operator('wm.blui_canvas_files', text=iface(label), icon=icon, translate=False)
            op.action = action
        layout.menu('FILEBROWSER_MT_explorer_more', text=iface('More'), icon='DOWNARROW_HLT', translate=False)
        layout.separator()
        layout.operator('node.view_all', text=iface('Frame All Cards'), translate=False)
        layout.operator('node.view_selected', text=iface('Frame Selected Cards'), translate=False)
        layout.operator('node.delete', text=iface('Remove Cards (Keep Files)'), icon='X', translate=False)
        layout.separator()
        op = layout.operator('wm.blui_canvas_transfer', text=iface('Copy To...'), icon='COPYDOWN', translate=False)
        op.move = False
        op = layout.operator('wm.blui_canvas_transfer', text=iface('Move To...'), icon='FILE_FOLDER', translate=False)
        op.move = True
        layout.separator()
        op = layout.operator('wm.blui_canvas_layout', text=iface('Save Layout'), icon='FILE_TICK', translate=False)
        op.action = 'SAVE'
        op = layout.operator('wm.blui_canvas_layout', text=iface('Restore Layout'), icon='FILE_REFRESH', translate=False)
        op.action = 'LOAD'


class BLUI_PT_canvas(Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Canvas'
    bl_label = 'Desktop Canvas'

    @classmethod
    def poll(cls, context):
        return canvas(context) is not None

    def draw(self, context):
        tree = canvas(context)
        self.layout.label(text=iface('Cards are references, not copies of files'), icon='INFO', translate=False)
        self.layout.prop(tree, 'directory')
        self.layout.operator('wm.blui_canvas_refresh')
        self.layout.menu('BLUI_MT_canvas_context')
        self.layout.prop(tree, 'board_name', text=iface('Desktop'))
        self.layout.prop(tree, 'monitor', text=iface('Display'))
        self.layout.label(text=session.autosave_status(), translate=False)


class BLUI_MT_desktop_widgets(Menu):
    bl_label = 'Widgets'

    def draw(self, _context):
        for kind, label, icon in ((widgets.CLOCK, 'Clock', 'TIME'),
                                  (widgets.CALCULATOR, 'Calculator', 'DRIVER'),
                                  (widgets.WEATHER, 'Weather', 'WORLD')):
            op = self.layout.operator('node.add_node', text=iface(label), icon=icon, translate=False)
            op.type, op.use_transform = kind, True


class BLUI_PT_canvas_tools(ToolSelectPanelHelper, Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'TOOLS'
    bl_label = 'Tools'
    bl_options = {'HIDE_HEADER'}
    keymap_prefix = 'Node Tool:'
    tool_fallback_id = 'builtin.select'
    _tools = {None: [
        ToolDef.from_dict(dict(idname='builtin.select', label='Tweak', icon='ops.generic.select')),
        ToolDef.from_dict(dict(idname='builtin.select_box', label='Select Box', icon='ops.generic.select_box',
            keymap=(('node.select_box', {'type': 'LEFTMOUSE', 'value': 'CLICK_DRAG'},
                     {'properties': [('wait_for_input', False), ('tweak', True), ('mode', 'SET')]}),))),
    ]}

    @classmethod
    def tools_all(cls):
        yield from cls._tools.items()

    @classmethod
    def tools_from_context(cls, _context, mode=None):
        yield from cls._tools[None]


classes = node_classes + groups.classes + widgets.classes + (BLUI_HT_canvas, BLUI_HT_taskbar, BLUI_MT_desktop_start,
                         BLUI_MT_desktop_tasks, BLUI_MT_canvas_context, BLUI_PT_canvas, BLUI_PT_canvas_tools)
classes += (BLUI_MT_desktop_widgets,)
