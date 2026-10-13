# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit desktop actions; file mutations reuse the existing isolated FIFO backend."""
import os
import json
import uuid
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from blui_desktop import model, native_windows, runtime, session
from blui_desktop.types import canvas
from blui_desktop.paths import desktop
from blui_explorer.localization import iface


def _file_workspace(context):
    return next((workspace for workspace in bpy.data.workspaces
                 if any(area.type == 'FILE_BROWSER' for screen in workspace.screens for area in screen.areas)), context.window.workspace)


def _new_window(context):
    before = {window.as_pointer() for window in context.window_manager.windows}
    result = bpy.ops.wm.window_new(workspace=_file_workspace(context).name)
    window = next((window for window in context.window_manager.windows if window.as_pointer() not in before), None)
    if result != {'FINISHED'} or not window:
        raise RuntimeError(iface('Could not open a desktop window'))
    return window


def _initialize(area, directory):
    area.type = 'NODE_EDITOR'
    space = area.spaces.active
    space.tree_type = model.TREE
    tree = bpy.data.node_groups.new('Desktop Canvas', model.TREE)
    tree.use_fake_user = True
    # A profile-wide default board is recoverable from a fresh session via Restore Layout.
    session.attach(tree)
    tree.service_identity = uuid.uuid4().hex
    tree.directory = directory
    space.node_tree, space.pin = tree, True
    space.show_region_ui = False
    space.show_region_toolbar = False
    if os.name == 'nt' and not session.disable_for_tests:
        from blui_desktop import taskbar
        taskbar.start(session.storage_directory())
    session.begin(runtime)
    if session.disable_for_tests or session._loaded:
        runtime.submit('scan', tree, directory)
    return tree


class CanvasAction:
    @classmethod
    def poll(cls, context):
        return canvas(context) is not None


class WM_OT_blui_desktop_open(Operator):
    bl_idname = 'wm.blui_desktop_open'
    bl_label = 'Desktop Canvas'
    bl_description = 'Open a native infinite canvas and taskbar without replacing the Windows desktop'
    bl_options = {'UNDO'}

    def execute(self, context):
        from bl_operators.blui_file import directory
        root = directory(context) or desktop()
        window = _new_window(context)
        _initialize(max(window.screen.areas, key=lambda area: area.width * area.height), root)
        return {'FINISHED'}


class WM_OT_blui_canvas_initialize(Operator):
    bl_idname = 'wm.blui_canvas_initialize'
    bl_label = 'Create Canvas'
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == 'NODE_EDITOR' and not canvas(context)

    def execute(self, context):
        _initialize(context.area, desktop())
        return {'FINISHED'}


class WM_OT_blui_canvas_refresh(CanvasAction, Operator):
    bl_idname = 'wm.blui_canvas_refresh'
    bl_label = 'Load Folder'
    bl_description = 'Add files from this folder without resetting manually arranged cards'

    def execute(self, context):
        tree = canvas(context)
        runtime.submit('scan', tree, tree.directory)
        return {'FINISHED'}


class WM_OT_blui_canvas_apply(CanvasAction, Operator):
    bl_idname = 'wm.blui_canvas_apply'
    bl_label = 'Update Canvas Cards'
    bl_options = {'UNDO', 'INTERNAL'}
    action: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    payload: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    origin: FloatVectorProperty(size=2, options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        tree = canvas(context)
        if runtime.interaction_busy(tree):
            return {'CANCELLED'}
        value = json.loads(self.payload)
        if self.action == 'load':
            runtime.apply_layout(tree, value)
            tree.service_status = iface('Canvas layout restored')
        elif self.action == 'scan':
            runtime.add_files(tree, value['rows'], origin=(0, -len(tree.nodes) * 30), selected=False)
            tree.service_status = iface('Folder snapshot loaded') + (' · ' + iface('Showing the first 1000 items') if value['truncated'] else '')
        elif self.action == 'paths':
            runtime.add_files(tree, value, self.origin)
            tree.service_status = iface('Folder snapshot loaded')
        else:
            return {'CANCELLED'}
        return {'FINISHED'}


class WM_OT_blui_canvas_import(CanvasAction, Operator, ImportHelper):
    bl_idname = 'wm.blui_canvas_import'
    bl_label = 'Add Files to Canvas'
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        paths = [os.path.join(self.directory, item.name) for item in self.files] or [self.filepath]
        runtime.submit('paths', canvas(context), paths)
        return {'FINISHED'}


class WM_OT_blui_canvas_drop(CanvasAction, Operator):
    bl_idname = 'wm.blui_canvas_drop'
    bl_label = 'Add Files to Canvas'
    bl_description = 'Add references at this location; no files are moved or deleted'
    bl_options = {'UNDO'}
    paths: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    has_drop_location: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    copy: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    drop_location: FloatVectorProperty(size=2, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        space = context.space_data
        space.cursor_location_from_region(event.mouse_region_x, event.mouse_region_y)
        self.drop_location, self.has_drop_location, self.copy = space.cursor_location, True, event.ctrl
        return self.execute(context)

    def execute(self, context):
        from blui_desktop import file_actions
        tree = canvas(context)
        paths = [path for path in self.paths.splitlines() if path]
        if not self.has_drop_location:
            runtime.submit('paths', tree, paths)
            return {'FINISHED'}
        origin = tuple(self.drop_location)
        context.space_data.cursor_location = origin
        # Cached native-node geometry only; never stat or resolve the hovered folder here.
        folder = next((node for node in tree.nodes if node.bl_idname == model.FILE and node.folder and
                       file_actions.absolute_location(node)[0] <= origin[0] <= file_actions.absolute_location(node)[0] + node.width and
                       file_actions.absolute_location(node)[1] - max(100, node.dimensions.y) <= origin[1] <= file_actions.absolute_location(node)[1]), None)
        if folder:
            file_actions.transfer(tree, paths, folder.filepath, move=not self.copy)
            file_actions.clear_drag()
            return {'FINISHED'}
        if file_actions.drop_references(tree, paths, origin, copy=self.copy):
            return {'FINISHED'}
        runtime.submit('paths', tree, paths)
        return {'FINISHED'}


class WM_OT_blui_canvas_note(CanvasAction, Operator):
    bl_idname = 'wm.blui_canvas_note'
    bl_label = 'Add Note Card'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        tree = canvas(context)
        if len(tree.nodes) >= model.LIMIT:
            self.report({'WARNING'}, iface('Showing the first 1000 items'))
            return {'CANCELLED'}
        node = tree.nodes.new(model.NOTE)
        node.location = context.space_data.cursor_location
        node.select = True
        tree.nodes.active = node
        return {'FINISHED'}


class WM_OT_blui_canvas_layout(CanvasAction, Operator):
    bl_idname = 'wm.blui_canvas_layout'
    bl_label = 'Canvas Layout'
    action: EnumProperty(items=(('SAVE', 'Save Layout', ''), ('LOAD', 'Restore Layout', '')))

    def execute(self, context):
        tree = canvas(context)
        path = runtime.layout_path(tree)
        if self.action == 'SAVE':
            runtime.submit('save', tree, path, runtime.snapshot(tree))
        else:
            runtime.submit('load', tree, path)
        return {'FINISHED'}


class WM_OT_blui_canvas_copy_path(Operator):
    bl_idname = 'wm.blui_canvas_copy_path'
    bl_label = 'Copy Path'
    filepath: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        context.window_manager.clipboard = self.filepath
        return {'FINISHED'}


class WM_OT_blui_canvas_open_file(Operator):
    bl_idname = 'wm.blui_canvas_open_file'
    bl_label = 'Open'
    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})
    folder: BoolProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        if self.folder:
            window = _new_window(context)
            area = max(window.screen.areas, key=lambda area: area.width * area.height)
            area.type = 'FILE_BROWSER'
            region = next((region for region in area.regions if region.type == 'WINDOW'), None)
            with context.temp_override(window=window, area=area, region=region):
                bpy.ops.file.select_bookmark(dir=self.filepath)
        else:
            runtime.submit('open', None, self.filepath)
        return {'FINISHED'}


class WM_OT_blui_canvas_transfer(CanvasAction, Operator):
    bl_idname = 'wm.blui_canvas_transfer'
    bl_label = 'Transfer Files'
    bl_description = 'Copy or move selected file cards with overwrite and descendant protection'
    directory: StringProperty(name='Destination Folder', subtype='DIR_PATH')
    move: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    paths: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    canvas_identity: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, _event):
        tree = canvas(context)
        self.paths = '\n'.join(node.filepath for node in tree.nodes if node.bl_idname == model.FILE and node.select)
        self.canvas_identity = json.dumps(runtime.identity(tree))
        if not self.paths:
            return {'CANCELLED'}
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        from bl_operators.blui_file import submit
        from blui_explorer import file_tasks
        paths = self.paths.splitlines()
        if not paths or not self.directory:
            return {'CANCELLED'}
        tree = runtime.resolve_tree(json.loads(self.canvas_identity)) if self.canvas_identity else canvas(context)
        if not tree:
            self.report({'WARNING'}, iface('Canvas changed; select the files again'))
            return {'CANCELLED'}
        token, destination, move = runtime.identity(tree), self.directory, self.move
        def finished():
            tree = runtime.resolve_tree(token)
            if tree and move:
                for node in tree.nodes:
                    if node.bl_idname == model.FILE and node.filepath in paths:
                        node.filepath = os.path.join(destination, os.path.basename(node.filepath))
        submit('Move' if move else 'Copy', file_tasks.transfer, paths, destination, move, on_success=finished)
        return {'FINISHED'}


class WM_OT_blui_task_activate(Operator):
    bl_idname = 'wm.blui_task_activate'
    bl_label = 'Activate Task'
    handle: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    pid: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})
    thread_id: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})
    process_started: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    window_class: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    minimize: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, _context):
        try:
            if not native_windows.act(self.handle, self.pid, self.minimize,
                    identity=(self.thread_id, self.process_started, self.window_class)):
                self.report({'WARNING'}, iface('Windows did not allow foreground activation'))
        except (RuntimeError, OSError, ValueError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


from blui_desktop.file_actions import classes as file_classes
from blui_desktop.background_types import classes as background_classes
from blui_desktop.displays import classes as display_classes
from blui_desktop.taskbar_ui import classes as taskbar_classes

classes = file_classes + background_classes + display_classes + taskbar_classes + (WM_OT_blui_desktop_open, WM_OT_blui_canvas_initialize, WM_OT_blui_canvas_refresh,
           WM_OT_blui_canvas_apply,
           WM_OT_blui_canvas_import, WM_OT_blui_canvas_drop, WM_OT_blui_canvas_note,
           WM_OT_blui_canvas_layout, WM_OT_blui_canvas_copy_path, WM_OT_blui_canvas_open_file,
           WM_OT_blui_canvas_transfer, WM_OT_blui_task_activate)


def _guard(method):
    def execute(self, context):
        try:
            return method(self, context)
        except (RuntimeError, OSError, ValueError, ReferenceError, StopIteration) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
    return execute


for _cls in classes:
    if hasattr(_cls, 'execute'):
        _cls.execute = _guard(_cls.execute)
