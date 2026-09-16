# SPDX-License-Identifier: GPL-2.0-or-later
"""BLUI Explorer menus. Native shell DLLs are hosted by shell_client's process."""

import os
import itertools
import sys
import time

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Menu, Operator
from bl_operators.blui_file import directory, selected_paths, refresh_all, task_status
from blui_explorer import file_tasks, shell_client

_bindings = {}
_dynamic = []
_regions = []
_menu_ids = itertools.count()


def _tick():
    for token, session in list(shell_client.sessions.items()):
        changed = session.poll()
        if changed:
            for node, items in session.items.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    child = item.get("submenu")
                    if child and (token, child) not in _bindings:
                        name = "FILEBROWSER_MT_shell_" + str(next(_menu_ids))
                        cls = type(name, (Menu,), {
                            "bl_label": item["label"] or "Windows",
                            "draw": _draw_native_submenu,
                            "session_token": token, "node_key": child,
                        })
                        bpy.utils.register_class(cls)
                        _dynamic.append(cls)
                        _bindings[token, child] = name
                        # Prefetch first-level extension submenus while the user
                        # reads the common actions. Further nesting stays lazy.
                        if node == "root":
                            session.request("expand", node=child)
            if session.items.pop("invoke", False):
                session.invoked = True
                refresh_all()
            if "invoke" in session.errors and not getattr(session, "error_shown", False):
                session.error_shown = True
                message = session.errors["invoke"]
                def draw_error(self, _context, message=message):
                    for start in range(0, len(message), 75):
                        self.layout.label(text=message[start:start + 75])
                bpy.context.window_manager.popup_menu(draw_error, title="Windows Command", icon='ERROR')
            for region in list(_regions):
                try:
                    region.tag_redraw()
                except ReferenceError:
                    _regions.remove(region)
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'FILE_BROWSER':
                        area.tag_redraw()
        if time.monotonic() - session.last_used > 300 and not session.pending:
            session.close()
            del shell_client.sessions[token]
    for cls in list(_dynamic):
        if cls.session_token not in shell_client.sessions:
            _bindings.pop((cls.session_token, cls.node_key), None)
            bpy.utils.unregister_class(cls)
            _dynamic.remove(cls)
    return 0.1 if shell_client.sessions else None


def _session(context, retry=False):
    paths = selected_paths(context) or [os.path.normpath(directory(context))]
    try:
        session = shell_client.get_session(paths, retry=retry)
        if not bpy.app.timers.is_registered(_tick):
            bpy.app.timers.register(_tick, first_interval=0.05)
        return session
    except (OSError, RuntimeError) as exc:
        print("BLUI Shell:", exc)
        return None


def _native_items(layout, context, session, node):
    if context.region and context.region not in _regions:
        _regions.append(context.region)
    if session is None:
        layout.label(text="Windows menu helper unavailable", icon='ERROR')
        return
    error = session.errors.get(node) or session.errors.get("invoke")
    if error:
        layout.label(text="Windows menu unavailable", icon='ERROR')
        layout.label(text=error[:80])
        layout.operator("file.explorer_shell_retry", text="Retry Windows Menu", icon='FILE_REFRESH')
        return
    if node not in session.items:
        if node != "root":
            session.request("expand", node=node)
        layout.label(text="Loading Windows menu...", icon='TIME')
        layout.label(text="Reopen this submenu when ready")
        return
    for item in session.items[node]:
        if item["separator"]:
            layout.separator()
            continue
        row = layout.row()
        row.enabled = item["enabled"]
        if item.get("submenu"):
            name = _bindings.get((session.token, item["submenu"]))
            if name:
                row.menu(name, text=item["label"], icon='FILE_FOLDER')
        else:
            op = row.operator("file.explorer_shell_command", text=item["label"], icon='FILEBROWSER')
            op.session_token, op.command = session.token, item["id"]


def _draw_native_submenu(self, context):
    _native_items(self.layout, context, shell_client.sessions.get(self.session_token), self.node_key)


class FILE_OT_explorer_shell_command(Operator):
    bl_idname = "file.explorer_shell_command"
    bl_label = "Run Windows Menu Command"
    session_token: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    command: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        session = shell_client.sessions.get(self.session_token)
        if session is None or session.process.poll() is not None:
            self.report({'ERROR'}, "This menu session expired. Open the context menu again.")
            return {'CANCELLED'}
        paths = tuple(selected_paths(context) or [os.path.normpath(directory(context))])
        if paths != session.paths:
            self.report({'ERROR'}, "Selection changed. Open the context menu again.")
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
            if not bpy.app.timers.is_registered(_tick):
                bpy.app.timers.register(_tick, first_interval=0.05)
        except (OSError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
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
    paths = selected_paths(context)
    if sys.platform == "win32":
        _session(context)  # Starts IPC only. Never waits for a shell extension.
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
        layout.menu("FILEBROWSER_MT_explorer_view", icon='RESTRICT_VIEW_OFF')
        layout.prop_menu_enum(context.space_data.params, "sort_method", text="Sort By")
        layout.operator("file.refresh", text="Refresh", icon='FILE_REFRESH')
        layout.separator()
        layout.operator("file.clipboard_paste", text="Paste", icon='PASTEDOWN')
        layout.menu("FILEBROWSER_MT_explorer_new", icon='ADD')
        layout.operator("file.explorer_copy_path", text="Copy Folder Path", icon='COPYDOWN')
        layout.operator("file.bookmark_add", text="Add to Favorites", icon='BOOKMARKS')
    if sys.platform == "win32":
        layout.separator()
        layout.menu("FILEBROWSER_MT_explorer_more", text="More", icon='THREE_DOTS')


def draw_toolbar(layout, context):
    layout.operator_context = 'INVOKE_REGION_WIN'
    row = layout.row(align=True)
    row.menu("FILEBROWSER_MT_explorer_new", text="New", icon='ADD')
    selected = bool(selected_paths(context))
    group = row.row(align=True)
    group.enabled = selected
    group.operator("file.clipboard_cut", text="Cut")
    group.operator("file.clipboard_copy", text="", icon='COPYDOWN')
    row.operator("file.clipboard_paste", text="", icon='PASTEDOWN')
    group = row.row(align=True)
    group.enabled = selected
    group.operator("file.explorer_rename", text="", icon='GREASEPENCIL')
    group.operator("file.delete", text="", icon='TRASH')
    row.menu("FILEBROWSER_MT_explorer_view", text="View")
    status = task_status()
    if status:
        layout.label(text=status, icon='INFO')


classes = (FILE_OT_explorer_shell_command, FILE_OT_explorer_shell_retry,
           FILE_OT_explorer_properties, FILEBROWSER_MT_explorer_more,
           FILEBROWSER_MT_explorer_view, FILEBROWSER_MT_explorer_new)
