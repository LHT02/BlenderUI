# SPDX-License-Identifier: GPL-2.0-or-later
"""Native Frame folder portals. Draws cached RNA; directory access stays in disposable jobs."""
import json
import ntpath
import uuid
import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel
from . import client, folder_panel_model, groups, model, serialization, session
from .types import canvas
from blui_explorer.localization import iface

_pending = []
_ready = []


def frame_by_id(tree, key):
    return next((node for node in tree.nodes if node.bl_idname == model.FRAME and
                 node.get('blui_id') == key), None)


def remaining_capacity(tree):
    """A shared group edit must fit every board that references it, not only the local tree."""
    roots = [tree] + [root for root in session.roots() if root != tree and tree in groups.trees(root)]
    return max(0, min(model.LIMIT - sum(1 for _owner, node in groups.walk(root)
                                      if node.bl_idname not in {'NodeGroupInput', 'NodeGroupOutput'})
                      for root in roots))


def request(tree, frame):
    from . import runtime
    serialization.identities(tree)
    path = folder_panel_model.directory(frame.get('blui_folder', ''))
    key = frame.get('blui_id', '')
    token = runtime.identity(tree)
    if any(old_token == token and old_key == key for _job, old_token, old_key, _path in _pending):
        return
    if len(_pending) + len(_ready) >= 4:
        raise RuntimeError('Desktop service is busy; try again shortly')
    _pending.append((client.Job('scan', path), token, key, path))
    tree.service_status = iface('Loading...')


def apply(tree, frame, value):
    key = frame['blui_id']
    existing = [{'id': node['blui_id'], 'path': node.filepath,
                 'managed': node.get('blui_portal_owner') == key}
                for node in tree.nodes if node.bl_idname == model.FILE and node.parent == frame]
    plan = folder_panel_model.changes(existing, value['rows'], remaining_capacity(tree),
                                     complete=not value['truncated'])
    by_id = {node.get('blui_id'): node for node in tree.nodes}
    for node_id in plan['remove']:
        tree.nodes.remove(by_id[node_id])
    for node_id, row in plan['update']:
        node = by_id[node_id]
        node.label, node.folder = row['name'], row['folder']
    # Existing positions are untouched; new children use the first empty grid cells.
    occupied = {(round(node.location.x / 150), round(-node.location.y / 140))
                for node in tree.nodes if node.parent == frame}
    cell = 0
    for row in plan['add']:
        while (cell % 6, cell // 6) in occupied:
            cell += 1
        node = tree.nodes.new(model.FILE)
        node.filepath, node.label, node.folder = row['path'], row['name'], row['folder']
        node.parent, node.location, node.select = frame, ((cell % 6) * 150, -(cell // 6) * 140), False
        node['blui_portal_owner'] = key
        cell += 1
    tree.service_status = iface('Folder panel refreshed')
    if value['truncated'] or plan['truncated']:
        tree.service_status += ' · ' + iface('Showing the first 1000 items')


def tick(runtime, live):
    for item in list(_pending):
        job, token, key, path = item
        if not job.done():
            continue
        _pending.remove(item)
        tree = runtime.resolve_tree(token)
        try:
            value = job.result()
            if tree:
                _ready.append((token, key, path, value))
        except (RuntimeError, ValueError, OSError) as exc:
            if tree:
                tree.service_status = str(exc)
    if runtime.interaction_busy(None):
        return
    for item in list(_ready):
        token, key, path, value = item
        tree = runtime.resolve_tree(token)
        frame = frame_by_id(tree, key) if tree else None
        if not frame or frame.get('blui_folder') != path:
            _ready.remove(item)
            continue
        owner = next(((win, area) for win, area in live if
                      (area.spaces.active.edit_tree or area.spaces.active.node_tree) == tree), None)
        if not owner:
            continue
        _ready.remove(item)
        win, area = owner
        region = next((region for region in area.regions if region.type == 'WINDOW'), None)
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.wm.blui_folder_panel_apply('EXEC_DEFAULT', True, frame=key, path=path,
                                                  payload=json.dumps(value))
        except (RuntimeError, ValueError, ReferenceError) as exc:
            tree = runtime.resolve_tree(token)
            if tree:
                tree.service_status = str(exc)


def close():
    for job, _token, _key, _path in _pending:
        job.close()
    _pending.clear()
    _ready.clear()


class WM_OT_blui_folder_panel_add(Operator):
    bl_idname = 'wm.blui_folder_panel_add'
    bl_label = 'Add Folder Panel'
    bl_description = 'Map a folder to an icon panel without moving or deleting real files'
    bl_options = {'UNDO'}
    directory: StringProperty(name='Folder', subtype='DIR_PATH')

    @classmethod
    def poll(cls, context):
        return canvas(context) is not None

    def invoke(self, context, _event):
        node = canvas(context).nodes.active
        if node and node.bl_idname == model.FILE and node.folder:
            self.directory = node.filepath
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        tree = canvas(context)
        folder_panel_model.directory(self.directory)
        if remaining_capacity(tree) < 1:
            raise ValueError('Showing the first 1000 items')
        frame = tree.nodes.new(model.FRAME)
        frame['blui_id'], frame['blui_folder'] = uuid.uuid4().hex, self.directory
        frame.label = ntpath.basename(ntpath.normpath(self.directory)) or self.directory
        frame.location, frame.width, frame.height = context.space_data.cursor_location, 900, 400
        frame.use_custom_color, frame.color = True, (0.10, 0.15, 0.20)
        tree.nodes.active = frame
        request(tree, frame)
        return {'FINISHED'}


class WM_OT_blui_folder_panel_refresh(Operator):
    bl_idname = 'wm.blui_folder_panel_refresh'
    bl_label = 'Refresh Folder Panel'
    frame: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return canvas(context) is not None

    def execute(self, context):
        tree = canvas(context)
        active = tree.nodes.active
        # Just-duplicated native Frames can temporarily share an ID. The sidebar
        # button belongs to the active Frame; request() will repair its ID before queuing.
        frame = (active if active and active.bl_idname == model.FRAME and
                 (not self.frame or active.get('blui_id') == self.frame)
                 else frame_by_id(tree, self.frame))
        if not frame or frame.bl_idname != model.FRAME:
            return {'CANCELLED'}
        request(tree, frame)
        return {'FINISHED'}


class WM_OT_blui_folder_panel_apply(Operator):
    bl_idname = 'wm.blui_folder_panel_apply'
    bl_label = 'Refresh Folder Panel'
    bl_options = {'UNDO', 'INTERNAL'}
    frame: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    path: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    payload: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        from . import runtime
        tree = canvas(context)
        frame = frame_by_id(tree, self.frame) if tree else None
        if not frame or frame.get('blui_folder') != self.path or runtime.interaction_busy(tree):
            return {'CANCELLED'}
        value = json.loads(self.payload)
        client._validate_value('scan', value)
        apply(tree, frame, value)
        return {'FINISHED'}


class BLUI_PT_folder_panel(Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Canvas'
    bl_label = 'Folder Panel'

    @classmethod
    def poll(cls, context):
        tree = canvas(context)
        node = tree.nodes.active if tree else None
        return node and node.bl_idname == model.FRAME and bool(node.get('blui_folder'))

    def draw(self, context):
        frame = canvas(context).nodes.active
        self.layout.prop(frame, 'label', text=iface('Display Label'))
        self.layout.label(text=frame.get('blui_folder', ''), icon='FILE_FOLDER', translate=False)
        self.layout.prop(frame, 'use_custom_color')
        self.layout.prop(frame, 'color', text=iface('Panel Color'))
        self.layout.operator('wm.blui_folder_panel_refresh').frame = frame['blui_id']
        self.layout.label(text=iface('Refreshing only changes references'), icon='INFO', translate=False)


class WM_OT_blui_canvas_frame_selected(Operator):
    bl_idname = 'wm.blui_canvas_frame_selected'
    bl_label = 'Frame Selected Cards'
    bl_description = 'Attach selected items to a new native frame without moving their visible positions'
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        tree = canvas(context)
        return bool(tree and any(node.select for node in tree.nodes))

    def execute(self, context):
        tree = canvas(context)
        if remaining_capacity(tree) < 1:
            raise ValueError('Showing the first 1000 items')
        result = bpy.ops.node.join('EXEC_DEFAULT')
        if result == {'FINISHED'}:
            frame = tree.nodes.active
            frame['blui_id'] = uuid.uuid4().hex
            frame.label = iface('Icon Panel')
        return result


classes = (WM_OT_blui_folder_panel_add, WM_OT_blui_folder_panel_refresh,
           WM_OT_blui_folder_panel_apply, BLUI_PT_folder_panel, WM_OT_blui_canvas_frame_selected)
