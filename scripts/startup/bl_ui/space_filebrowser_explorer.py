# SPDX-License-Identifier: GPL-2.0-or-later
"""Explorer actions plus Blender's original file-browser context commands."""

import os
import sys

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Menu, Operator
from bl_operators.blui_file import directory, selected_paths, task_status
from blui_explorer import file_tasks, shell_client
from blui_explorer.localization import iface, message
from bl_ui import space_filebrowser_shell as shell_ui

# Kept for scripts that inspected the previous module's session bindings.
_bindings = shell_ui.bindings
_session = shell_ui.session


def _native_items(layout, context, session, node):
    if session is None:
        layout.label(text="Windows menu helper unavailable", icon='ERROR')
        return
    layout.enable_popup_refresh(shell_ui.popup_key(session, node))
    error = session.errors.get(node) or session.errors.get("invoke")
    if error:
        layout.label(text="Windows menu unavailable", icon='ERROR')
        layout.label(text=message(error)[:80], translate=False)
        layout.operator("file.explorer_shell_retry", text="Retry Windows Menu", icon='FILE_REFRESH')
        return
    if node not in session.items:
        if node != "root":
            session.request("expand", node=node)
        layout.label(text="Loading Windows menu...", icon='TIME')
        return
    for item in session.items[node]:
        if item["separator"]:
            layout.separator()
            continue
        row = layout.row()
        row.enabled = item["enabled"]
        if item.get('localize'):
            row.label(text=message(item['label']), icon='TIME' if item.get('loading') else 'ERROR', translate=False)
            if not item.get('loading'):
                layout.operator("file.explorer_shell_retry", text="Retry Windows Menu", icon='FILE_REFRESH')
            continue
        if item.get("submenu"):
            name = _bindings.get((session.token, item["submenu"]))
            if name:
                row.menu(name, text=item["label"], icon='FILE_FOLDER', translate=False)
        else:
            op = row.operator("file.explorer_shell_command", text=item["label"], icon='FILEBROWSER', translate=False)
            op.session_token, op.command = session.token, item["id"]


class FILE_OT_explorer_shell_command(Operator):
    bl_idname = "file.explorer_shell_command"
    bl_label = "Run Windows Menu Command"
    session_token: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    command: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        session = shell_client.sessions.get(self.session_token)
        if session is None or not session.is_alive():
            self.report({'ERROR'}, iface("This menu session expired. Open the context menu again."))
            return {'CANCELLED'}
        paths = tuple(selected_paths(context) or [os.path.normpath(directory(context))])
        if paths != session.paths:
            self.report({'ERROR'}, iface("Selection changed. Open the context menu again."))
            return {'CANCELLED'}
        session.request("invoke", command=self.command)
        return {'FINISHED'}


class FILE_OT_explorer_shell_retry(Operator):
    bl_idname = "file.explorer_shell_retry"
    bl_label = "Retry Windows Menu"

    def execute(self, context):
        _session(context, retry=True)
        return {'FINISHED'}


class FILE_OT_explorer_properties(Operator):
    bl_idname = "file.explorer_properties"
    bl_label = "Properties"

    def execute(self, context):
        try:
            if len(shell_client.sessions) >= 8:
                raise RuntimeError("Close existing Windows extension dialogs before opening another")
            paths = selected_paths(context) or [directory(context)]
            session = shell_client.Session(paths[:1], action="properties")
            session.invoked = True
            shell_client.sessions[session.token] = session
            shell_ui.ensure_tick()
        except (OSError, RuntimeError) as exc:
            self.report({'ERROR'}, message(str(exc)))
            return {'CANCELLED'}
        return {'FINISHED'}


class FILEBROWSER_MT_explorer_more(Menu):
    bl_label = "More"

    def draw(self, context):
        layout = self.layout
        paths = selected_paths(context)
        if paths:
            layout.operator("file.explorer_reveal", text="Open File Location", icon='FILE_FOLDER')
        layout.operator("file.explorer_properties", text="Properties", icon='INFO')
        layout.separator()
        layout.label(text="Windows Context Menu")
        _native_items(layout, context, _session(context), "root")


class FILEBROWSER_MT_explorer_view(Menu):
    bl_label = "View"

    def draw(self, context):
        params = context.space_data.params
        self.layout.prop_enum(params, "display_type", 'LIST_VERTICAL', text="Details")
        self.layout.prop_enum(params, "display_type", 'LIST_HORIZONTAL', text="List")
        self.layout.prop_enum(params, "display_type", 'THUMBNAIL', text="Large Icons")
        self.layout.separator()
        self.layout.prop(params, "show_hidden", text="Hidden Items")


class FILEBROWSER_MT_explorer_new(Menu):
    bl_label = "New"

    def draw(self, _context):
        self.layout.operator_context = 'EXEC_REGION_WIN'
        self.layout.operator("file.directory_new", text="Folder", icon='NEWFOLDER').confirm = False
        self.layout.operator_context = 'INVOKE_REGION_WIN'
        self.layout.operator("file.explorer_new_file", text="Text Document", icon='FILE_TEXT')


def draw_context_menu(layout, context):
    layout.operator_context = 'INVOKE_REGION_WIN'
    layout.ui_units_x = 18
    paths = selected_paths(context)
    params = context.space_data.params
    if sys.platform == "win32":
        _session(context)

    # Preserve the original Blender navigation and external operations.
    layout.operator("file.previous", text="Back")
    layout.operator("file.next", text="Forward")
    layout.operator("file.parent", text="Go to Parent")
    layout.operator("file.refresh", text="Refresh")
    layout.menu("FILEBROWSER_MT_operations_menu")
    layout.separator()
    layout.operator("file.filenum", text="Increase Number", icon='ADD').increment = 1
    layout.operator("file.filenum", text="Decrease Number", icon='REMOVE').increment = -1
    layout.separator()

    if paths:
        row = layout.row()
        row.enabled = len(paths) == 1
        row.operator("file.execute", text="Open", icon='FILE_FOLDER')
        layout.operator("file.explorer_rename", text="Rename", icon='GREASEPENCIL')
        layout.operator("file.delete", text="Move to Recycle Bin", icon='TRASH')
        layout.separator()
        layout.operator("file.clipboard_cut", text="Cut")
        layout.operator("file.clipboard_copy", text="Copy", icon='COPYDOWN')
        layout.operator("file.clipboard_paste", text="Paste", icon='PASTEDOWN')
        layout.operator("file.explorer_transfer", text="Copy To...", icon='DUPLICATE').move = False
        layout.operator("file.explorer_transfer", text="Move To...", icon='FILE_FOLDER').move = True
        layout.operator("file.explorer_copy_path", text="Copy Path", icon='COPYDOWN')
        layout.separator()
        layout.operator("file.explorer_extract", text="Extract ZIP to Folder...", icon='PACKAGE')
        layout.operator("file.explorer_archive", text="Create ZIP...", icon='PACKAGE').kind = 'ZIP'
        row = layout.row()
        row.enabled = bool(file_tasks.seven_zip())
        row.operator("file.explorer_archive", text="Create 7Z...", icon='PACKAGE').kind = '7Z'
    else:
        layout.operator("file.clipboard_paste", text="Paste", icon='PASTEDOWN')
        layout.operator("file.explorer_copy_path", text="Copy Folder Path", icon='COPYDOWN')

    layout.separator()
    row = layout.row()
    row.operator_context = 'EXEC_REGION_WIN'
    row.operator("file.directory_new", text="New Folder", icon='NEWFOLDER').confirm = False
    layout.operator("file.explorer_new_file", text="Text Document", icon='FILE_TEXT')
    layout.operator("file.bookmark_add", text="Add Bookmark", icon='BOOKMARKS')
    layout.separator()
    layout.prop_menu_enum(params, "display_type")
    if params.display_type == 'THUMBNAIL':
        layout.prop_menu_enum(params, "display_size")
    layout.prop_menu_enum(params, "recursion_level", text="Recursions")
    layout.prop_menu_enum(params, "sort_method")

    if sys.platform == "win32":
        layout.separator()
        layout.menu("FILEBROWSER_MT_explorer_more", text="More", icon='THREE_DOTS')


def draw_status(layout, _context):
    status = task_status()
    if status:
        layout.label(text=status, icon='INFO', translate=False)


classes = (FILE_OT_explorer_shell_command, FILE_OT_explorer_shell_retry,
           FILE_OT_explorer_properties, FILEBROWSER_MT_explorer_more,
           FILEBROWSER_MT_explorer_view, FILEBROWSER_MT_explorer_new)
