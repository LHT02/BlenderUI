# SPDX-License-Identifier: GPL-2.0-or-later
"""Explorer actions. Menu presentation and native Shell sessions live elsewhere."""

import json
import os
import time
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator
from blui_explorer import file_tasks, task_client

_jobs = []
_status = ("", 0.0)


def task_status():
    if _jobs:
        return _jobs[0][1] + "..." + (" (%d queued)" % (len(_jobs) - 1) if len(_jobs) > 1 else "")
    return _status[0] if time.monotonic() - _status[1] < 12 else ""


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'FILE_BROWSER':
                area.tag_redraw()


def directory(context):
    space = context.space_data
    return os.fsdecode(space.params.directory) if space and space.type == 'FILE_BROWSER' and space.params else ""


def selected_paths(context):
    root = directory(context)
    if not root:
        return []
    return [os.path.normpath(os.path.join(root, entry.relative_path))
            for entry in (getattr(context, "selected_files", None) or ())
            if entry.relative_path not in {"", ".", ".."}]


def _refresh_now():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'FILE_BROWSER':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    if bpy.ops.file.refresh.poll():
                        bpy.ops.file.refresh()
                area.tag_redraw()
    return None


def refresh_all():
    # File refresh invalidates FileSelectEntry RNA pointers. Defer it until the
    # invoking operator/menu and its context override have unwound.
    if not bpy.app.timers.is_registered(_refresh_now):
        bpy.app.timers.register(_refresh_now, first_interval=0.05)


def _finish_jobs():
    global _status
    for future, label, on_success in list(_jobs):
        if not future.done():
            break  # FIFO: only one process may mutate files at a time.
        _jobs.remove((future, label, on_success))
        try:
            result = future.result()
            message = label + " completed"
            print("BLUI FILE:", message, result)
            if on_success:
                on_success()
            _status = (message, time.monotonic())
        except Exception as exc:
            message = str(exc)
            print("BLUI FILE ERROR:", message)
            _status = (label + " failed", time.monotonic())
            def draw(self, _context, text=message):
                for start in range(0, len(text), 85):
                    self.layout.label(text=text[start:start + 85])
            bpy.context.window_manager.popup_menu(draw, title=label, icon='ERROR')
        refresh_all()
    _redraw()
    return 0.15 if _jobs else None


def submit(label, fn, *args, on_success=None):
    _jobs.append((task_client.Job(fn, args), label, on_success))
    _redraw()
    if not bpy.app.timers.is_registered(_finish_jobs):
        bpy.app.timers.register(_finish_jobs, first_interval=0.15)


class FileSelection:
    @classmethod
    def poll(cls, context):
        return bool(selected_paths(context))


class FILE_OT_explorer_copy_path(Operator):
    bl_idname = "file.explorer_copy_path"
    bl_label = "Copy Path"
    bl_description = "Copy the full paths of the selected items, or the current folder"

    @classmethod
    def poll(cls, context):
        return bool(directory(context))

    def execute(self, context):
        context.window_manager.clipboard = "\n".join(selected_paths(context) or [directory(context)])
        return {'FINISHED'}


class FILE_OT_explorer_rename(FileSelection, Operator):
    bl_idname = "file.explorer_rename"
    bl_label = "Rename"
    bl_description = "Rename this item without overwriting another file"
    name: StringProperty(name="Name", options={'SKIP_SAVE'})
    source: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return len(selected_paths(context)) == 1

    def invoke(self, context, _event):
        self.source = selected_paths(context)[0]
        self.name = os.path.basename(self.source)
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        paths = selected_paths(context)
        source = self.source or (paths[0] if paths else "")
        try:
            file_tasks.valid_name(self.name)
            target = os.path.join(os.path.dirname(source), self.name)
            if target != source:
                if os.path.exists(target) and file_tasks.canonical(target) != file_tasks.canonical(source):
                    raise FileExistsError("An item with that name already exists")
                os.rename(source, target)
            refresh_all()
        except (OSError, ValueError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class FILE_OT_explorer_new_file(Operator):
    bl_idname = "file.explorer_new_file"
    bl_label = "New Text File"
    name: StringProperty(name="Name", default="New Text Document.txt", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return bool(directory(context))

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        try:
            file_tasks.valid_name(self.name)
            with open(os.path.join(directory(context), self.name), "x", encoding="utf-8"):
                pass
            refresh_all()
        except (OSError, ValueError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class FILE_OT_explorer_transfer(FileSelection, Operator):
    bl_idname = "file.explorer_transfer"
    bl_label = "Choose Destination Folder"
    bl_description = "Copy or move selected items to a folder; existing files are never overwritten"
    directory: StringProperty(subtype='DIR_PATH')
    sources: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    move: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, _event):
        self.sources = json.dumps(selected_paths(context))
        self.directory = directory(context)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        paths = json.loads(self.sources) if self.sources else selected_paths(context)
        submit("Move" if self.move else "Copy", file_tasks.transfer, paths, self.directory, self.move)
        return {'FINISHED'}


class FILE_OT_explorer_archive(FileSelection, Operator):
    bl_idname = "file.explorer_archive"
    bl_label = "Create Archive"
    kind: EnumProperty(items=(('ZIP', "ZIP", ""), ('7Z', "7Z", "")), options={'SKIP_SAVE'})
    name: StringProperty(name="Archive name", options={'SKIP_SAVE'})
    sources: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, _event):
        paths = selected_paths(context)
        self.sources = json.dumps(paths)
        self.name = (Path(paths[0]).stem if len(paths) == 1 else "Archive") + "." + self.kind.lower()
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        paths = json.loads(self.sources) if self.sources else selected_paths(context)
        try:
            file_tasks.valid_name(self.name)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        submit("Create " + self.kind, file_tasks.archive, paths,
               str(Path(paths[0]).parent / self.name), self.kind)
        return {'FINISHED'}


class FILE_OT_explorer_extract(FileSelection, Operator):
    bl_idname = "file.explorer_extract"
    bl_label = "Extract ZIP to Folder"
    bl_description = "Extract into a new sibling folder; use the 7-Zip system submenu for other formats"

    @classmethod
    def poll(cls, context):
        paths = selected_paths(context)
        return len(paths) == 1 and paths[0].lower().endswith(".zip")

    def execute(self, context):
        source = selected_paths(context)[0]
        submit("Extract ZIP", file_tasks.extract_zip, source, os.path.splitext(source)[0])
        return {'FINISHED'}


class FILE_OT_explorer_reveal(FileSelection, Operator):
    bl_idname = "file.explorer_reveal"
    bl_label = "Open File Location"
    bl_description = "Show the selected item in Windows Explorer"

    def execute(self, context):
        import subprocess
        paths = selected_paths(context)
        subprocess.Popen([os.path.join(os.environ['WINDIR'], 'explorer.exe'), '/select,', paths[0]])
        return {'FINISHED'}


class FILE_OT_explorer_drop(Operator):
    bl_idname = "file.explorer_drop"
    bl_label = "Drop Files"
    directory: StringProperty(subtype='DIR_PATH')
    sources: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    move: BoolProperty(options={'SKIP_SAVE'})
    from_clipboard: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, _context):
        paths = [p for p in self.sources.splitlines() if p]
        if not paths or not self.directory:
            self.report({'ERROR'}, "No files or destination for this drop")
            return {'CANCELLED'}
        on_success = None
        if self.from_clipboard and self.move:
            from blui_explorer import clipboard_win32
            sequence = clipboard_win32.sequence()
            on_success = lambda: clipboard_win32.clear_if_unchanged(sequence)
        submit("Move" if self.move else "Copy", file_tasks.transfer, paths, self.directory, self.move,
               on_success=on_success)
        return {'FINISHED'}


classes = (FILE_OT_explorer_copy_path, FILE_OT_explorer_rename, FILE_OT_explorer_new_file,
           FILE_OT_explorer_transfer, FILE_OT_explorer_archive, FILE_OT_explorer_extract,
           FILE_OT_explorer_reveal, FILE_OT_explorer_drop)
