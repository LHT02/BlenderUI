# SPDX-License-Identifier: GPL-2.0-or-later
"""Strict portable desktop graphs, shared groups and native frame parenting."""
import uuid
from . import model, groups

FIELDS = {model.CLOCK: ('clock_format', 'date_format'), model.CALCULATOR: ('expression',),
          model.WEATHER: ('city', 'latitude', 'longitude', 'weather_source', 'weather_enabled'),
          model.FRAME: ('label_size', 'shrink', 'height')}
BACKGROUND = ('path', 'enabled', 'fit', 'opacity', 'align_x', 'align_y')


def valid_id(key):
    return isinstance(key, str) and len(key) == 32 and all(char in '0123456789abcdef' for char in key)


def identities(owner):
    """Native Frame duplication copies ID props; repair IDs and only truly managed children."""
    keys = set()
    for node in owner.nodes:
        old = node.get('blui_id', '')
        if not valid_id(old) or old in keys:
            key = node['blui_id'] = uuid.uuid4().hex
            if node.bl_idname == model.FRAME and old:
                for child in owner.nodes:
                    if child.parent == node and child.get('blui_portal_owner') == old:
                        child['blui_portal_owner'] = key
        else:
            key = old
        keys.add(key)


def snapshot(tree):
    seen = {}
    def encode(node):
        if node.bl_idname not in {model.FILE, model.NOTE, model.FRAME, model.GROUP,
                                  model.CLOCK, model.CALCULATOR, model.WEATHER}:
            return None
        owner = node.id_data.as_pointer()
        keys = seen.setdefault(owner, set())
        key = node.get('blui_id', '')
        if not valid_id(key) or key in keys:
            key = node['blui_id'] = uuid.uuid4().hex
        keys.add(key)
        props = {'width': node.width}
        props.update((field, getattr(node, field)) for field in FIELDS.get(node.bl_idname, ()))
        if node.bl_idname == model.FRAME:
            props.update(folder_path=node.get('blui_folder', ''),
                         use_custom_color=getattr(node, 'use_custom_color', False),
                         color=list(getattr(node, 'color', (0.608, 0.608, 0.608))))
        elif node.bl_idname == model.FILE:
            props['portal_owner'] = node.get('blui_portal_owner', '')
        row = {'id': key, 'kind': node.bl_idname, 'location': list(node.location),
               'name': node.label, 'path': getattr(node, 'filepath', ''),
               'folder': getattr(node, 'folder', False), 'note': getattr(node, 'note', ''), 'props': props}
        return row
    # Assign frame IDs before children, independent of native node list ordering.
    for owner in groups.trees(tree):
        identities(owner)
    result = groups.serialize(tree, encode)
    by_tree = {owner.as_pointer(): owner for owner in groups.trees(tree)}
    # Parent identities are local to a tree; group serializer preserves shared references.
    def attach(rows, owner):
        by_id = {node.get('blui_id'): node for node in owner.nodes}
        for row in rows:
            node = by_id[row['id']]
            if node.parent:
                row['parent'] = node.parent['blui_id']
    attach(result['nodes'], tree)
    # Match group records by traversal insertion order, the serializer's gN mapping.
    owners = []
    seen_owners = {tree.as_pointer()}
    def collect(current):
        for node in current.nodes:
            if node.bl_idname == model.GROUP and node.node_tree and node.node_tree.as_pointer() not in seen_owners:
                seen_owners.add(node.node_tree.as_pointer())
                owners.append(node.node_tree)
                collect(node.node_tree)
    collect(tree)
    for record, owner in zip(result['groups'], owners):
        attach(record['nodes'], owner)
    result.update(version=2, directory=tree.directory)
    if hasattr(tree, 'background_path'):
        result['background'] = {field: getattr(tree, 'background_' + field) for field in BACKGROUND}
    return model.validate(result)


def decode(tree, row):
    node = tree.nodes.new(row['kind'])
    node['blui_id'] = row.get('id', uuid.uuid4().hex)
    node.location, node.label = row['location'], row['name']
    node.width = row['props']['width']
    node.select = False
    if row['kind'] == model.FILE:
        node.filepath, node.folder = row['path'], row['folder']
        if row['props'].get('portal_owner'):
            node['blui_portal_owner'] = row['props']['portal_owner']
    elif row['kind'] == model.FRAME:
        if row['props'].get('folder_path'):
            node['blui_folder'] = row['props']['folder_path']
        node.use_custom_color = row['props'].get('use_custom_color', False)
        node.color = row['props'].get('color', (0.608, 0.608, 0.608))
    elif row['kind'] == model.NOTE:
        node.note = row['note']
    for field in FIELDS.get(row['kind'], ()):
        setattr(node, field, row['props'][field])
    return node


def finish(tree, rows):
    by_id = {node.get('blui_id'): node for node in tree.nodes}
    for node, row in zip(tree.nodes, rows):
        if row.get('parent'):
            node.parent = by_id[row['parent']]
            node.location = row['location']


def apply(tree, payload):
    payload = model.validate(payload)
    groups.restore(tree, payload, decode, finish_tree=finish)
    tree.directory = payload['directory']
    for field, value in payload.get('background', {}).items():
        setattr(tree, 'background_' + field, value)
