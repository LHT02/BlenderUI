# SPDX-License-Identifier: GPL-2.0-or-later
"""Real native node groups for desktop references, without an evaluation engine."""
import bpy
import uuid
from bpy.types import NodeCustomGroup
from blui_explorer.localization import iface
from . import model

GROUP = 'BLUIDesktopGroup'
MAX_DEPTH = 16


def walk(tree, *, unique=True):
    """Visit actual referenced trees, bounded even for malformed or recursive files.

    ``unique`` visits a linked group's data only once. Use ``False`` when counting
    visible instances, not when updating the real file references they share.
    """
    total, visited = 0, set()

    def visit(current, ancestors):
        nonlocal total
        if not current or current.bl_idname != model.TREE:
            return
        pointer = current.as_pointer()
        if pointer in ancestors or len(ancestors) >= MAX_DEPTH:
            raise ValueError('Invalid recursive desktop group')
        if unique and pointer in visited:
            return
        visited.add(pointer)
        for node in current.nodes:
            total += 1
            if total > model.LIMIT:
                raise ValueError('Desktop group contains too many cards')
            yield current, node
            if node.bl_idname == GROUP and node.node_tree:
                yield from visit(node.node_tree, ancestors | {pointer})

    yield from visit(tree, set())


def trees(tree):
    """Actual native data blocks, including an otherwise empty root or group."""
    result, seen = [], set()

    def visit(current, ancestors):
        if not current or current.bl_idname != model.TREE:
            return
        pointer = current.as_pointer()
        if pointer in ancestors or len(ancestors) >= MAX_DEPTH:
            raise ValueError('Invalid recursive desktop group')
        if pointer in seen:
            return
        seen.add(pointer)
        if len(seen) > model.LIMIT:
            raise ValueError('Desktop contains too many groups')
        result.append(current)
        for node in current.nodes:
            if node.bl_idname == GROUP and node.node_tree:
                visit(node.node_tree, ancestors | {pointer})

    visit(tree, set())
    return result


def file_nodes(tree):
    for owner, node in walk(tree):
        if node.bl_idname == model.FILE:
            yield owner, node


def serialize(tree, encode_node):
    """Return ``nodes`` and a DAG of native group data blocks.

    The caller encodes its whitelisted card/widget properties. Group references
    are always handled here so two instances of one native group remain linked.
    Empty native input/output placeholders have no desktop evaluation meaning
    and are deliberately omitted from the portable layout.
    """
    ids, records, ancestors = {}, [], set()
    count = 0

    def encode(current, depth):
        nonlocal count
        if not current or current.bl_idname != model.TREE:
            raise ValueError('Invalid desktop group type')
        pointer = current.as_pointer()
        if pointer in ancestors or depth >= MAX_DEPTH:
            raise ValueError('Invalid recursive desktop group')
        ancestors.add(pointer)
        rows = []
        try:
            for node in current.nodes:
                if node.bl_idname in {'NodeGroupInput', 'NodeGroupOutput'}:
                    continue
                count += 1
                if count > model.LIMIT:
                    raise ValueError('Desktop group contains too many cards')
                row = encode_node(node)
                if node.bl_idname == GROUP:
                    if row is None:
                        row = {'kind': GROUP, 'name': node.label,
                               'location': list(node.location), 'props': {'width': node.width}}
                    else:
                        row = dict(row)
                    child = node.node_tree
                    if child:
                        if child.bl_idname != model.TREE or child.as_pointer() in ancestors:
                            raise ValueError('Invalid recursive desktop group')
                        child_pointer = child.as_pointer()
                        if child_pointer not in ids:
                            key = ids[child_pointer] = 'g' + str(len(ids) + 1)
                            record = {'id': key, 'name': child.get('blui_group_name', child.name), 'directory': child.directory}
                            records.append(record)
                            record['nodes'] = encode(child, depth + 1)
                        row['group'] = ids[child_pointer]
                    else:
                        row['group'] = None
                if row is not None:
                    rows.append(row)
        finally:
            ancestors.remove(pointer)
        return rows

    rows = encode(tree, 0)
    return {'nodes': rows, 'groups': records}


def validate_graph(payload):
    """Cheap independent graph checks, before any RNA data is allocated or cleared."""
    records = payload.get('groups', [])
    roots = payload.get('nodes')
    if not isinstance(records, list) or not isinstance(roots, list):
        raise ValueError('Invalid desktop group layout')
    by_id, total = {}, len(roots)
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('Invalid desktop group')
        key, rows = record.get('id'), record.get('nodes')
        if not isinstance(key, str) or not key or key in by_id or not isinstance(rows, list):
            raise ValueError('Invalid desktop group identity')
        by_id[key] = record
        total += len(rows)
    if total > model.LIMIT:
        raise ValueError('Desktop group contains too many cards')
    visited, heights = set(), {}

    def height(rows, ancestors):
        result = 0
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Invalid desktop card')
            if row.get('kind') != GROUP:
                if 'group' in row:
                    raise ValueError('Only desktop groups can reference another tree')
                continue
            key = row.get('group')
            if key is None:
                continue
            if not isinstance(key, str) or key not in by_id or key in ancestors:
                raise ValueError('Invalid recursive desktop group')
            visited.add(key)
            # Memoize group height, not "visited depth". This stays linear for a
            # highly shared DAG and still validates every possible nesting depth.
            if key not in heights:
                if len(ancestors) >= MAX_DEPTH:
                    raise ValueError('Desktop group is too deeply nested')
                heights[key] = height(by_id[key]['nodes'], ancestors | {key})
            result = max(result, 1 + heights[key])
            if result >= MAX_DEPTH:
                raise ValueError('Desktop group is too deeply nested')
        return result

    height(roots, set())
    if len(visited) != len(by_id):
        raise ValueError('Desktop layout contains unreachable groups')
    return by_id


def restore(tree, payload, decode_node, finish_tree=None):
    """Rebuild real group data and only then replace a previously validated root.

    ``decode_node(owner_tree, descriptor)`` returns a card built from the caller's
    strict property allowlist. It must not invoke files, scripts, or operators.
    This includes group cards' shared identity, location and display properties.
    ``finish_tree(owner_tree, descriptors)`` optionally reconnects same-tree frame
    parents after every node is created, using the descriptors' stable IDs.
    A temporary root preflights every descriptor before the existing root is
    cleared; validation failures leave the old board untouched.
    """
    if tree.bl_idname != model.TREE:
        raise ValueError('Invalid desktop group type')
    by_id = validate_graph(payload)
    created = {}
    shadow = None

    def decode(current, rows):
        for row in rows:
            node = decode_node(current, row)
            if node is None or node.bl_idname != row['kind']:
                raise ValueError('Invalid desktop card restoration')
            if row['kind'] == GROUP:
                node.node_tree = created.get(row.get('group'))
        if finish_tree:
            finish_tree(current, rows)

    try:
        for key, record in by_id.items():
            child = bpy.data.node_groups.new(record.get('name') or iface('Desktop Group'), model.TREE)
            # Portable display names are distinct from Blender's globally unique ID names.
            # Never rename or delete an older group still referenced by another board.
            child['blui_group_name'] = record.get('name') or iface('Desktop Group')
            created[key] = child
            child.directory = record.get('directory', '')
        for key, record in by_id.items():
            decode(created[key], record['nodes'])
        shadow = bpy.data.node_groups.new('Desktop Layout Validation', model.TREE)
        decode(shadow, payload['nodes'])
        tree.nodes.clear()
        decode(tree, payload['nodes'])
    except Exception:
        if shadow:
            bpy.data.node_groups.remove(shadow)
        for child in reversed(list(created.values())):
            bpy.data.node_groups.remove(child)
        raise
    bpy.data.node_groups.remove(shadow)
    return created


class BLUI_DesktopGroup(NodeCustomGroup):
    bl_idname = GROUP
    bl_label = 'Desktop Group'
    bl_icon = 'NODETREE'

    @classmethod
    def poll(cls, tree):
        return tree.bl_idname == model.TREE

    def init(self, _context):
        self.width = 260
        self['blui_id'] = uuid.uuid4().hex

    def copy(self, _node):
        self['blui_id'] = uuid.uuid4().hex

    def draw_label(self):
        return self.label or (self.node_tree.get('blui_group_name', self.node_tree.name) if self.node_tree else iface('Desktop Group'))

    def draw_buttons(self, _context, layout):
        group = self.node_tree
        if not group:
            layout.label(text=iface('Empty Group'), icon='INFO', translate=False)
            return
        # Cached RNA only: never resolve shortcuts or query the filesystem here.
        layout.label(text=iface('Tab: Enter or Exit Group'), icon='NODETREE', translate=False)
        displayed = 0
        try:
            for _owner, node in file_nodes(group):
                if displayed == 8:
                    layout.label(text='…', translate=False)
                    break
                op = layout.operator('wm.blui_canvas_open_file', text=node.label,
                                     icon='FILE_FOLDER' if node.folder else 'FILE', translate=False)
                op.filepath, op.folder = node.filepath, node.folder
                displayed += 1
        except (ValueError, ReferenceError):
            layout.label(text=iface('Invalid Desktop Group'), icon='ERROR', translate=False)


classes = (BLUI_DesktopGroup,)
