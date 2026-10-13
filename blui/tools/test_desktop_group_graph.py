# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure bounded desktop-group graph checks; no bpy runtime or GUI required."""
import copy
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
from blui_desktop import model

bpy = ModuleType('bpy')
bpy_types = ModuleType('bpy.types')
bpy_types.NodeCustomGroup = type('NodeCustomGroup', (), {})
localization = ModuleType('blui_explorer.localization')
localization.iface = lambda text: text
spec = importlib.util.spec_from_file_location('blui_desktop.groups', SOURCE / 'scripts/modules/blui_desktop/groups.py')
groups = importlib.util.module_from_spec(spec)
with mock.patch.dict(sys.modules, {'bpy': bpy, 'bpy.types': bpy_types, 'blui_explorer.localization': localization}):
    spec.loader.exec_module(groups)


def group_row(key):
    return {'kind': groups.GROUP, 'name': 'test', 'location': [0, 0], 'props': {}, 'group': key}


class Tree:
    bl_idname = model.TREE
    directory = ''
    def __init__(self, name, nodes):
        self.name, self.nodes = name, nodes
        self.properties = {}
    def get(self, key, default=None):
        return self.properties.get(key, default)
    def __setitem__(self, key, value):
        self.properties[key] = value
    def as_pointer(self):
        return id(self)


def card(kind=model.FILE, child=None):
    return SimpleNamespace(bl_idname=kind, node_tree=child, label='fixture', filepath='private.txt',
                           folder=False, location=(3, -4), width=260)


class GroupGraphs(unittest.TestCase):
    def test_shared_native_group_is_serialized_once(self):
        child = Tree('Shared', [card()])
        root = Tree('Root', [card(groups.GROUP, child), card(groups.GROUP, child)])
        payload = groups.serialize(root, lambda node: None if node.bl_idname == groups.GROUP else
            {'kind': node.bl_idname, 'name': node.label, 'location': list(node.location),
             'props': {'filepath': node.filepath, 'folder': node.folder}})
        self.assertEqual(len(payload['groups']), 1)
        self.assertEqual(payload['nodes'][0]['group'], payload['nodes'][1]['group'])
        self.assertEqual(len(list(groups.file_nodes(root))), 1)
        self.assertEqual(len(groups.trees(root)), 2)
        groups.validate_graph(payload)

    def test_direct_indirect_and_malformed_cycles_are_rejected(self):
        first, second = Tree('A', []), Tree('B', [])
        first.nodes.append(card(groups.GROUP, second))
        second.nodes.append(card(groups.GROUP, first))
        with self.assertRaisesRegex(ValueError, 'recursive'):
            groups.serialize(first, lambda _node: None)
        with self.assertRaisesRegex(ValueError, 'recursive'):
            list(groups.walk(first))
        payload = {'nodes': [group_row('a')], 'groups': [
            {'id': 'a', 'nodes': [group_row('b')]}, {'id': 'b', 'nodes': [group_row('a')]}]}
        with self.assertRaisesRegex(ValueError, 'recursive'):
            groups.validate_graph(payload)

    def test_max_depth_is_enforced_for_every_shared_path(self):
        records = [{'id': 'g' + str(i), 'nodes': [group_row('g' + str(i + 1))]}
                   for i in range(groups.MAX_DEPTH - 1)]
        records.append({'id': 'g' + str(groups.MAX_DEPTH - 1), 'nodes': []})
        payload = {'nodes': [group_row('g' + str(groups.MAX_DEPTH - 1)), group_row('g0')], 'groups': records}
        with self.assertRaisesRegex(ValueError, 'nested'):
            groups.validate_graph(payload)
        # The short branch primes the cache, but must not hide a later deep path.
        payload['nodes'] = [group_row('g1')]
        payload['groups'] = records[1:]
        groups.validate_graph(payload)

    def test_highly_shared_dag_stays_bounded(self):
        records = [{'id': 'g' + str(i), 'nodes': [group_row('g' + str(i + 1))] * 40}
                   for i in range(14)]
        records.append({'id': 'g14', 'nodes': []})
        payload = {'nodes': [group_row('g0')] * 40, 'groups': records}
        groups.validate_graph(payload)

    def test_unknown_duplicate_or_unreachable_groups_are_rejected(self):
        cases = (
            {'nodes': [group_row('missing')], 'groups': []},
            {'nodes': [], 'groups': [{'id': 'a', 'nodes': []}]},
            {'nodes': [group_row('a')], 'groups': [{'id': 'a', 'nodes': []}, {'id': 'a', 'nodes': []}]},
            {'nodes': [{'kind': model.FILE, 'group': 'a'}], 'groups': []},
        )
        for payload in cases:
            with self.assertRaises(ValueError):
                groups.validate_graph(payload)

    def test_budget_and_wrong_tree_are_rejected_without_mutation(self):
        root = Tree('Root', [card()])
        before = list(root.nodes)
        with self.assertRaisesRegex(ValueError, 'too many'):
            groups.restore(root, {'nodes': [group_row(None)] * (model.LIMIT + 1)}, None)
        self.assertEqual(root.nodes, before)
        wrong = Tree('Wrong', [])
        wrong.bl_idname = 'AnotherCustomTree'
        root.nodes.append(card(groups.GROUP, wrong))
        with self.assertRaises(ValueError):
            groups.serialize(root, lambda _node: None)


if __name__ == '__main__':
    unittest.main()
