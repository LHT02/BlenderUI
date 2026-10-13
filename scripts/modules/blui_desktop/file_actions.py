# SPDX-License-Identifier: GPL-2.0-or-later
"""Explorer-style desktop actions using the existing native clipboard and safe FIFO."""
import json
import os
import time
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator
from . import model, runtime, groups
from .types import canvas
from blui_explorer.localization import iface

_drag = None


def clear_drag():
    global _drag
    _drag = None


def absolute_location(node):
    point = list(node.location)
    parent, seen = node.parent, set()
    while parent:
        key = parent.as_pointer()
        if key in seen or len(seen) >= 16:
            raise ValueError('Invalid icon panel parent')
        seen.add(key)
        point[0] += parent.location.x
        point[1] += parent.location.y
        parent = parent.parent
    return point


def selected_nodes(context):
    tree = canvas(context)
    if not tree:
        return []
    result = []
    for node in tree.nodes:
        selected = node.select
        parent = node.parent
        ancestors = set()
        while parent and not selected:
            if parent.as_pointer() in ancestors or len(ancestors) >= 16:
                raise ValueError('Invalid icon panel parent')
            ancestors.add(parent.as_pointer())
            selected = parent.select
            parent = parent.parent
        if node.bl_idname == model.FILE and selected:
            result.append(node)
    for group in tree.nodes:
        if group.bl_idname == model.GROUP and group.select and group.node_tree:
            result.extend(node for _owner, node in groups.file_nodes(group.node_tree))
    return result


def selected_paths(context):
    return list(dict.fromkeys(node.filepath for node in selected_nodes(context) if node.filepath))


def retarget(token, mapping):
    tree = runtime.resolve_tree(token)
    if tree:
        for _owner, node in groups.file_nodes(tree):
            if node.filepath in mapping:
                node.filepath = mapping[node.filepath]
                node.label = os.path.basename(node.filepath)


def transfer(tree, paths, destination, move=False, from_clipboard=False):
    from bl_operators.blui_file import submit
    from blui_explorer import file_tasks, clipboard_win32
    token = runtime.identity(tree)
    sequence = clipboard_win32.sequence() if from_clipboard and move else 0
    targets = [os.path.join(destination, os.path.basename(path)) for path in paths]
    def finished():
        current = runtime.resolve_tree(token)
        if move:
            retarget(token, dict(zip(paths, targets)))
        if current:
            runtime.submit('paths', current, targets)
        if sequence:
            clipboard_win32.clear_if_unchanged(sequence)
    submit('Move' if move else 'Copy', file_tasks.transfer, paths, destination, move, on_success=finished)


class WM_OT_blui_canvas_open_active(Operator):
    bl_idname = 'wm.blui_canvas_open_active'
    bl_label = 'Open'

    @classmethod
    def poll(cls, context):
        return bool(selected_nodes(context))

    def execute(self, context):
        nodes = selected_nodes(context)
        node = nodes[0]
        return bpy.ops.wm.blui_canvas_open_file(filepath=node.filepath, folder=node.folder)


class WM_OT_blui_canvas_files(Operator):
    bl_idname = 'wm.blui_canvas_files'
    bl_label = 'File Action'
    action: EnumProperty(items=tuple((key, label, '') for key, label in
        (('COPY', 'Copy'), ('CUT', 'Cut'), ('PASTE', 'Paste'), ('RENAME', 'Rename'), ('RECYCLE', 'Delete to Recycle Bin'))))
    name: StringProperty(name='Name')
    paths: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    tree_identity: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return canvas(context) is not None

    def invoke(self, context, _event):
        paths = selected_paths(context)
        if self.action in {'RENAME', 'RECYCLE'}:
            if not paths or self.action == 'RENAME' and len(paths) != 1:
                return {'CANCELLED'}
            self.paths, self.tree_identity = json.dumps(paths), json.dumps(runtime.identity(canvas(context)))
            self.name = os.path.basename(paths[0])
            return context.window_manager.invoke_props_dialog(self, width=420) if self.action == 'RENAME' else context.window_manager.invoke_confirm(self, _event)
        return self.execute(context)

    def execute(self, context):
        paths = json.loads(self.paths) if self.paths else selected_paths(context)
        if self.action == 'PASTE':
            return bpy.ops.file.clipboard_paste()
        if self.action in {'COPY', 'CUT'}:
            if not paths:
                return {'CANCELLED'}
            operator = bpy.ops.file.clipboard_cut if self.action == 'CUT' else bpy.ops.file.clipboard_copy
            return operator(paths='\n'.join(paths))
        from bl_operators.blui_file import submit
        from . import file_services
        tree = runtime.resolve_tree(json.loads(self.tree_identity)) if self.tree_identity else canvas(context)
        if not tree:
            return {'CANCELLED'}
        token = runtime.identity(tree)
        if self.action == 'RENAME':
            from blui_explorer.file_tasks import valid_name
            valid_name(self.name)
            target = os.path.join(os.path.dirname(paths[0]), self.name)
            submit('Rename', file_services.rename, paths[0], target,
                   on_success=lambda: retarget(token, {paths[0]: target}))
        else:
            submit('Delete to Recycle Bin', file_services.isolated_recycle, paths)
        return {'FINISHED'}


class WM_OT_blui_canvas_paste(Operator):
    bl_idname = 'wm.blui_canvas_paste'
    bl_label = 'Paste Files'
    sources: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH')
    move: BoolProperty()
    from_clipboard: BoolProperty()

    def execute(self, context):
        tree = canvas(context)
        if not tree:
            return {'CANCELLED'}
        transfer(tree, self.sources.splitlines(), self.directory, self.move, self.from_clipboard)
        return {'FINISHED'}


class WM_OT_blui_canvas_drag_prepare(Operator):
    bl_idname = 'wm.blui_canvas_drag_prepare'
    bl_label = 'Drag Desktop Icons'
    bl_options = {'INTERNAL'}
    filepath: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        global _drag
        tree = canvas(context)
        if not tree:
            return {'CANCELLED'}
        node = next((node for node in tree.nodes if node.bl_idname == model.FILE and node.filepath == self.filepath), None)
        if not node:
            return {'CANCELLED'}
        if not node.select:
            for item in tree.nodes:
                item.select = item == node
        tree.nodes.active = node
        nodes = [node for node in tree.nodes if node.select and node.bl_idname == model.FILE]
        _drag = {'token': runtime.identity(tree), 'fingerprint': runtime.fingerprint(tree),
                 'ids': [node['blui_id'] for node in nodes], 'paths': [node.filepath for node in nodes],
                 'started': time.monotonic()}
        return {'FINISHED'}


def drop_references(target, paths, origin, copy=False):
    global _drag
    drag, _drag = _drag, None
    if not drag or time.monotonic() - drag['started'] > 120 or paths != drag['paths']:
        return False
    source = runtime.resolve_tree(drag['token'])
    if not source or runtime.fingerprint(source) != drag['fingerprint']:
        raise ValueError(iface('Canvas changed; select the files again'))
    if runtime.interaction_busy(None):
        raise ValueError(iface('Canvas update cancelled'))
    if source == target and not copy:
        nodes = [node for node in source.nodes if node.get('blui_id') in drag['ids']]
        positions = [absolute_location(node) for node in nodes]
        anchor = positions[0]
        for node, position in zip(nodes, positions):
            parent = absolute_location(node.parent) if node.parent else (0, 0)
            node.location = (origin[0] + position[0] - anchor[0] - parent[0], origin[1] + position[1] - anchor[1] - parent[1])
        return True
    # Stage destination first. Native source nodes are never removed if allocation fails.
    staged = []
    try:
        nodes = [node for node in source.nodes if node.get('blui_id') in drag['ids']]
        if len(target.nodes) + len(nodes) > model.LIMIT:
            raise ValueError('Destination desktop contains too many cards')
        anchor = absolute_location(nodes[0])
        for node in nodes:
            new = target.nodes.new(model.FILE)
            staged.append(new)
            new.filepath, new.folder, new.label = node.filepath, node.folder, node.label
            position = absolute_location(node)
            new.location = (origin[0] + position[0] - anchor[0], origin[1] + position[1] - anchor[1])
    except Exception:
        for new in staged:
            target.nodes.remove(new)
        raise
    if not copy:
        for node in nodes:
            source.nodes.remove(node)
    return True


classes = (WM_OT_blui_canvas_open_active, WM_OT_blui_canvas_files, WM_OT_blui_canvas_paste,
           WM_OT_blui_canvas_drag_prepare)
