# SPDX-License-Identifier: GPL-2.0-or-later
"""Strict desktop v2 layout/adapter regressions; no Blender, native API, or user CONFIG.

Run with the bundled Python: python -B blui/tools/test_desktop_layout_v2.py.
RNA doubles exercise actual graph serialization and session recovery code, while
filesystem tests use only an owned TemporaryDirectory.
"""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
from blui_desktop import autosave, boards, model


def row(kind=model.FILE, key='a' * 32, **extra):
    result = {'id': key, 'kind': kind, 'location': [12, -34], 'name': '测试 fixture',
              'path': 'D:\\private-fixture\\test.txt', 'folder': False, 'note': '', 'props': {}}
    result.update(extra)
    return result


def layout(nodes=None, groups=None):
    return {'version': 2, 'directory': 'D:\\private-fixture',
            'nodes': nodes or [], 'groups': groups or []}


class Point(list):
    @property
    def x(self):
        return self[0]

    @property
    def y(self):
        return self[1]

    def copy(self):
        return Point(self)


class Node(dict):
    def __init__(self, owner, kind):
        super().__init__()
        self.id_data, self.bl_idname = owner, kind
        self.name = str(len(owner.nodes))
        self.location, self.label, self.width, self.height = [0, 0], '', 240, 120
        self.filepath, self.folder, self.note = '', False, ''
        self.parent, self.node_tree = None, None
        self.select = False
        self.clock_format, self.date_format = '%H:%M:%S', '%Y-%m-%d'
        self.expression, self.result = '', ''
        self.city, self.latitude, self.longitude = '杭州', 30.2741, 120.1551
        self.weather_source, self.weather_enabled = 'AUTO', False
        self.label_size, self.shrink = 20, True

    def __bool__(self):
        return True

    def __setattr__(self, key, value):
        object.__setattr__(self, key, Point(value) if key == 'location' else value)

    def as_pointer(self):
        return id(self)


class Nodes(list):
    def __init__(self, tree):
        super().__init__()
        self.tree = tree

    def new(self, kind):
        value = Node(self.tree, kind)
        self.append(value)
        return value


class Tree:
    bl_idname = model.TREE

    def __init__(self, name):
        self.properties = {}
        self.name, self.nodes, self.directory = name, Nodes(self), ''
        self.board_id = self.layout_key = self.monitor = self.service_identity = ''
        self.board_name, self.service_status, self.use_fake_user = 'Desktop', '', False
        self.background_path, self.background_enabled, self.background_fit = '', False, 'FILL'
        self.background_opacity, self.background_align_x, self.background_align_y = 1, 0, 0

    def get(self, key, default=None):
        return self.properties.get(key, default)

    def __setitem__(self, key, value):
        self.properties[key] = value

    def as_pointer(self):
        return id(self)


class Trees(list):
    def new(self, name, kind):
        if kind != model.TREE:
            raise ValueError('Only fixture desktop trees are allowed')
        value = Tree(name)
        self.append(value)
        return value


RNA = ModuleType('bpy')
RNA.data = SimpleNamespace(node_groups=Trees())
RNA.utils = SimpleNamespace(user_resource=mock.Mock(side_effect=AssertionError('No user CONFIG access')))
RNA_TYPES = ModuleType('bpy.types')
RNA_TYPES.NodeCustomGroup = type('NodeCustomGroup', (), {})
RNA_TYPES.Operator = type('Operator', (), {})
LOCALIZATION = ModuleType('blui_explorer.localization')
LOCALIZATION.iface = lambda text: text


def load_adapter(name):
    fullname = 'blui_desktop.' + name
    spec = importlib.util.spec_from_file_location(fullname, SOURCE / 'scripts/modules/blui_desktop' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {'bpy': RNA, 'bpy.types': RNA_TYPES,
                                      'blui_explorer.localization': LOCALIZATION}):
        spec.loader.exec_module(module)
    sys.modules[fullname] = module
    setattr(sys.modules['blui_desktop'], name, module)
    return module


groups = load_adapter('groups')
serialization = load_adapter('serialization')
session = load_adapter('session')
RNA_PROPS = ModuleType('bpy.props')
for property_name in ('BoolProperty', 'EnumProperty', 'StringProperty'):
    setattr(RNA_PROPS, property_name, lambda **_kwargs: None)
DESKTOP_TYPES = ModuleType('blui_desktop.types')
DESKTOP_TYPES.canvas = lambda context: context.tree
RUNTIME = ModuleType('blui_desktop.runtime')
RUNTIME._epoch = 0
RUNTIME.identity = lambda tree: (tree.as_pointer(), tree.service_identity, RUNTIME._epoch)
RUNTIME.resolve_tree = lambda token: next((tree for tree in RNA.data.node_groups
    if token and RUNTIME.identity(tree) == token), None)
RUNTIME.fingerprint = lambda tree: boards.fingerprint_layout(serialization.snapshot(tree))
RUNTIME.interaction_busy = lambda _tree: False
with mock.patch.dict(sys.modules, {'bpy.props': RNA_PROPS, 'blui_desktop.types': DESKTOP_TYPES,
                                  'blui_desktop.runtime': RUNTIME}):
    setattr(sys.modules['blui_desktop'], 'runtime', RUNTIME)
    file_actions = load_adapter('file_actions')


class SchemaV2(unittest.TestCase):
    def assert_invalid(self, value):
        before = copy.deepcopy(value)
        with self.assertRaises(ValueError):
            model.validate(value)
        self.assertEqual(value, before, 'Validation must never edit its input')

    def test_legacy_layout_is_normalized_without_losing_fields(self):
        original = {'version': 1, 'directory': '测试 folder', 'nodes': [
            {'kind': model.NOTE, 'location': [2.25, -12], 'note': 'saved note'}]}
        result = model.validate(original)
        self.assertEqual(result['version'], 2)
        self.assertEqual(result['nodes'][0]['note'], 'saved note')
        self.assertEqual(result['nodes'][0]['location'], [2.25, -12])
        self.assertNotIn('props', original['nodes'][0])

    def test_widget_and_wallpaper_preferences_round_trip(self):
        value = layout([row(model.CLOCK, props={'clock_format': '%I:%M %p', 'date_format': '%A'}),
                        row(model.CALCULATOR, 'b' * 32, props={'expression': 'sqrt(9)+pi'}),
                        row(model.WEATHER, 'c' * 32, props={'city': '深圳', 'latitude': 22.54,
                            'longitude': 114.06, 'weather_source': 'CMA', 'weather_enabled': False})])
        value['background'] = {'enabled': True, 'path': 'transparent.png', 'fit': 'SPAN',
                               'opacity': .4, 'align_x': -1, 'align_y': 1}
        result = model.validate(value)
        self.assertEqual(result['nodes'][0]['props']['date_format'], '%A')
        self.assertEqual(result['nodes'][1]['props']['expression'], 'sqrt(9)+pi')
        self.assertFalse(result['nodes'][2]['props']['weather_enabled'])
        self.assertEqual(result['background'], value['background'])
        self.assertEqual(model.validate(result), result)

    def test_invalid_properties_fail_with_value_error_before_restoration(self):
        for kind, prop, value in ((model.FILE, 'width', 10 ** 1000),
                                 (model.FRAME, 'label_size', False),
                                 (model.WEATHER, 'latitude', float('inf')),
                                 (model.WEATHER, 'longitude', -181),
                                 (model.CALCULATOR, 'expression', 'x' * 513)):
            with self.subTest(kind=kind, prop=prop):
                self.assert_invalid(layout([row(kind, props={prop: value})]))

    def test_background_invalid_type_does_not_escape_as_type_error(self):
        for key, value in (('fit', []), ('opacity', 10 ** 1000), ('enabled', 1),
                           ('align_x', float('nan')), ('path', 'bad\x00file')):
            payload = layout()
            payload['background'] = {key: value}
            with self.subTest(key=key):
                self.assert_invalid(payload)

    def test_duplicate_ids_invalid_hex_and_nonfinite_coordinates_rejected(self):
        self.assert_invalid(layout([row(), row(model.NOTE)]))
        for key in ('A' * 32, 'q' * 32, 'a' * 31, []):
            self.assert_invalid(layout([row(key=key)]))
        for position in ([True, 0], [0, float('inf')], [1e8, 0]):
            self.assert_invalid(layout([row(location=position)]))

    def test_frame_parenting_is_same_tree_and_order_independent(self):
        value = layout([row(parent='b' * 32), row(model.FRAME, 'b' * 32)])
        result = model.validate(value)
        self.assertEqual(result['nodes'][0]['parent'], 'b' * 32)
        self.assert_invalid(layout([row(parent='b' * 32), row(model.NOTE, 'b' * 32)]))

    def test_nested_missing_frame_parent_is_value_error_even_if_child_first(self):
        self.assert_invalid(layout([row(parent='b' * 32),
                                    row(model.FRAME, 'b' * 32, parent='c' * 32)]))

    def test_recursive_frame_and_group_graphs_rejected(self):
        self.assert_invalid(layout([row(model.FRAME, parent='b' * 32),
                                    row(model.FRAME, 'b' * 32, parent='a' * 32)]))
        self.assert_invalid(layout([row(model.GROUP, group='g1')], [
            {'id': 'g1', 'nodes': [row(model.GROUP, group='g2')]},
            {'id': 'g2', 'nodes': [row(model.GROUP, group='g1')]}]))

    def test_frame_depth_matches_the_reference_drag_limit(self):
        def nested(depth):
            keys = [f'{index + 100:032x}' for index in range(depth)]
            rows = [row(parent=keys[0])]
            for index, key in enumerate(keys):
                rows.append(row(model.FRAME, key, **({'parent': keys[index + 1]}
                                  if index + 1 < depth else {})))
            return layout(rows)
        model.validate(nested(16))
        self.assert_invalid(nested(17))

    def test_shared_groups_persist_once_and_local_ids_do_not_conflict(self):
        value = layout([row(model.GROUP, group='g1'), row(model.GROUP, 'b' * 32, group='g1')],
                       [{'id': 'g1', 'name': 'Shared', 'nodes': [row(model.NOTE)]}])
        clean = model.validate(value)
        self.assertEqual(len(clean['groups']), 1)
        self.assertEqual(clean['nodes'][0]['group'], clean['nodes'][1]['group'])

    def test_hidden_group_cards_count_toward_global_budget(self):
        value = layout([row(model.GROUP, group='g1')], [{'id': 'g1', 'nodes': [
            row(model.NOTE, f'{index:032x}') for index in range(model.LIMIT)]}])
        self.assert_invalid(value)

    def test_backup_recovery_preserves_complete_shared_graph_and_background(self):
        with tempfile.TemporaryDirectory(prefix='blui_layout_v2_') as folder:
            target = Path(folder) / 'canvas.json'
            value = layout([row(model.GROUP, group='g1')],
                           [{'id': 'g1', 'nodes': [row(model.CLOCK)]}])
            value['background'] = {'path': 'fixture.png', 'enabled': True, 'fit': 'FIT', 'opacity': .25}
            model.save(target, value)
            model.save(target, layout([row(model.NOTE)]))
            target.write_bytes(b'{truncated-own-fixture')
            restored = model.load(target)
            self.assertEqual(restored, model.validate(value))
            self.assertFalse(list(Path(folder).glob('*.tmp')))


class AdapterV2(unittest.TestCase):
    def setUp(self):
        RNA.data.node_groups.clear()
        session._collection = session._restore = None
        session._loading = session._loaded = False
        session._expected = {}
        session._snapshot_error = ''
        session.disable_for_tests = False
        session._scheduler = autosave.Scheduler(lambda *_args: self.fail('No filesystem jobs in adapter test'))
        self.temporary = tempfile.TemporaryDirectory(prefix='blui_session_v2_')
        self.env = mock.patch.dict(os.environ, {'BLUI_DESKTOP_CONFIG': self.temporary.name})
        self.env.start()
        self.runtime = SimpleNamespace(_epoch=0, interaction_busy=lambda _tree: False,
                                       submit=mock.Mock(), fingerprint=lambda tree:
                                       boards.fingerprint_layout(serialization.snapshot(tree)))

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()
        session.disable_for_tests = True
        session._scheduler.reset()

    def root(self):
        tree = RNA.data.node_groups.new('Fixture', model.TREE)
        session.attach(tree, 'QA display', '\\\\.\\DISPLAY99')
        return tree

    def test_snapshot_ids_are_stable_and_duplicates_are_repaired(self):
        tree = self.root()
        first, second = tree.nodes.new(model.FILE), tree.nodes.new(model.NOTE)
        first['blui_id'] = second['blui_id'] = 'b' * 32
        before = serialization.snapshot(tree)
        after = serialization.snapshot(tree)
        self.assertEqual(before, after)
        self.assertNotEqual(before['nodes'][0]['id'], before['nodes'][1]['id'])

    def test_snapshot_repairs_malformed_native_ids(self):
        for bad in (123, None, 'q' * 32, 'A' * 32):
            with self.subTest(bad=bad):
                tree = self.root()
                node = tree.nodes.new(model.FILE)
                node['blui_id'] = bad
                result = serialization.snapshot(tree)
                self.assertTrue(boards.uuid_key(result['nodes'][0]['id']))

    def test_restore_reconnects_nested_frames_widgets_and_shared_native_groups(self):
        tree = self.root()
        parent, child = tree.nodes.new(model.FRAME), tree.nodes.new(model.FILE)
        parent.label, parent.location, parent.width = 'Desktop panel', [-30, 220], 620
        child.parent, child.location, child.filepath = parent, [20, -70], 'D:\\fixture\\a.txt'
        shared = RNA.data.node_groups.new('Shared clock', model.TREE)
        shared.nodes.new(model.CLOCK).clock_format = '%I:%M %p'
        shared.nodes.new(model.CALCULATOR).expression = 'sqrt(16)'
        one, two = tree.nodes.new(model.GROUP), tree.nodes.new(model.GROUP)
        one.node_tree = two.node_tree = shared
        payload = serialization.snapshot(tree)
        serialization.apply(tree, payload)
        self.assertEqual(serialization.snapshot(tree), payload)
        new_parent, new_child, new_one, new_two = tree.nodes
        self.assertIs(new_child.parent, new_parent)
        self.assertEqual(new_child.location, [20, -70])
        self.assertIs(new_one.node_tree, new_two.node_tree)
        self.assertEqual(new_one.node_tree.nodes[1].expression, 'sqrt(16)')
        self.assertFalse(any(value.name == 'Desktop Layout Validation' for value in RNA.data.node_groups))

    def test_invalid_restore_does_not_touch_native_root(self):
        tree = self.root()
        sentinel = tree.nodes.new(model.NOTE)
        sentinel.note = 'Do not replace this live edit'
        before = list(tree.nodes)
        invalid = layout([row(parent='b' * 32)])
        with self.assertRaises(ValueError):
            serialization.apply(tree, invalid)
        self.assertEqual(tree.nodes, before)
        self.assertEqual(sentinel.note, 'Do not replace this live edit')

    def test_large_manual_frame_keeps_its_height_and_width_across_recovery(self):
        tree = self.root()
        panel = tree.nodes.new(model.FRAME)
        panel.width, panel.height, panel.shrink = 4100, 640, False
        saved = serialization.snapshot(tree)
        self.assertEqual(saved['nodes'][0]['props']['height'], 640)
        serialization.apply(tree, saved)
        self.assertEqual(tree.nodes[0].width, 4100)
        self.assertEqual(tree.nodes[0].height, 640)
        self.assertFalse(tree.nodes[0].shrink)

    def test_native_group_preflight_failure_keeps_root_and_removes_staging_trees(self):
        tree = self.root()
        sentinel = tree.nodes.new(model.NOTE)
        payload = model.validate(layout([row(model.GROUP, group='g1')],
                              [{'id': 'g1', 'nodes': [row(model.FILE)]}]))
        count = len(RNA.data.node_groups)
        def fail_decode(owner, descriptor):
            if descriptor['kind'] == model.FILE:
                raise RuntimeError('Owned allocation fixture failure')
            return serialization.decode(owner, descriptor)
        with self.assertRaises(RuntimeError):
            groups.restore(tree, payload, fail_decode)
        self.assertEqual(tree.nodes, [sentinel])
        self.assertEqual(len(RNA.data.node_groups), count)

    def test_collection_preserves_disconnected_display_and_increments_only_on_edits(self):
        tree = self.root()
        tree.nodes.new(model.NOTE).note = 'Saved display'
        first, second = session.collection(), session.collection()
        self.assertEqual(first, second)
        tree.nodes[0].location = [50, -20]
        third = session.collection()
        self.assertGreater(third['revision'], first['revision'])
        self.assertGreater(third['boards'][0]['revision'], first['boards'][0]['revision'])
        RNA.data.node_groups.remove(tree)
        self.assertEqual(session.collection()['boards'][0]['monitor'], '\\\\.\\DISPLAY99')

    def test_async_restore_never_overwrites_an_already_edited_same_id_board(self):
        tree = self.root()
        sentinel = tree.nodes.new(model.NOTE)
        sentinel.note = 'Older saved layout'
        saved = session.collection()
        session.begin(self.runtime)
        # The real helper completes after a user has edited the existing board.
        sentinel.note = 'New unsaved user edit'
        session.receive(saved)
        session.tick(self.runtime)
        self.assertTrue(any(node.note == 'New unsaved user edit' for node in tree.nodes),
                        'Late startup recovery discarded live edits with the same board ID')

    def test_modal_delays_recovery_without_losing_queued_snapshot(self):
        saved = boards.new_collection('Saved monitor', layout([row(model.NOTE, note='Recovered note')]))
        session.receive(saved)
        self.runtime.interaction_busy = lambda _tree: True
        session.tick(self.runtime)
        self.assertIsNotNone(session._restore)
        self.assertFalse(RNA.data.node_groups)
        self.runtime.interaction_busy = lambda _tree: False
        session.tick(self.runtime)
        self.assertTrue(session._loaded)
        self.assertEqual(RNA.data.node_groups[0].nodes[0].note, 'Recovered note')

    def test_worker_admission_failure_does_not_leave_loading_without_a_job(self):
        self.root()
        self.runtime.submit.side_effect = RuntimeError('Owned busy fixture')
        with self.assertRaises(RuntimeError):
            session.begin(self.runtime)
        self.assertFalse(session._loading)
        self.runtime.submit.side_effect = None
        session.begin(self.runtime)
        self.assertTrue(session._loading)

    def test_ready_recovery_is_not_submitted_again_before_its_safe_apply(self):
        saved = boards.new_collection('Recovered display', layout([row(model.NOTE, note='Recovered note')]))
        session.receive(saved)
        session.begin(self.runtime)
        self.runtime.submit.assert_not_called()
        self.assertIsNotNone(session._restore)

    def test_initial_undo_reset_allows_one_fresh_recovery_request(self):
        tree = self.root()
        tree.nodes.new(model.NOTE).note = 'Initial board'
        session.begin(self.runtime)
        self.assertTrue(session._loading)
        session.reset(1)
        self.assertFalse(session._loading)
        self.runtime._epoch = 1
        session.begin(self.runtime)
        self.assertEqual(self.runtime.submit.call_count, 2)
        self.assertTrue(session._loading)

    def test_overbudget_snapshot_reports_error_without_escaping_or_losing_live_nodes(self):
        tree = self.root()
        for _index in range(model.LIMIT + 1):
            tree.nodes.new(model.NOTE)
        session._loaded = True
        self.assertIsNone(session.tick(self.runtime))
        self.assertIn('too many cards', session.autosave_status())
        self.assertEqual(tree.service_status, session.autosave_status())
        self.assertEqual(len(tree.nodes), model.LIMIT + 1)
        self.assertIsNone(session._scheduler.pending)
        # A bpy timer's next services are reached; no exception unregisters the callback.
        next_service = mock.Mock()
        next_service()
        next_service.assert_called_once()
        tree.nodes.pop()
        session.tick(self.runtime)
        self.assertFalse(session._snapshot_error)
        self.assertTrue(session._scheduler.dirty)
        self.assertIn('Unsaved', session.autosave_status())

    def test_snapshot_failure_on_second_board_rolls_back_revision_records_then_recovers(self):
        first, second = self.root(), self.root()
        first.nodes.new(model.NOTE).note = 'Previously saved edit'
        second.nodes.new(model.NOTE).note = 'Previously saved second board'
        session._loaded = True
        session.tick(self.runtime)
        before = copy.deepcopy(session._collection)
        first.nodes[0].note = 'New edit must remain saveable'
        for _index in range(model.LIMIT):
            second.nodes.new(model.NOTE)
        session.tick(self.runtime)
        self.assertEqual(session._collection, before)
        self.assertEqual(first.nodes[0].note, 'New edit must remain saveable')
        self.assertIn('too many cards', session.autosave_status())
        second.nodes.pop()
        session.tick(self.runtime)
        self.assertFalse(session._snapshot_error)
        self.assertGreater(session._collection['revision'], before['revision'])
        self.assertEqual(session._scheduler.pending['boards'][0]['layout']['nodes'][0]['note'],
                         'New edit must remain saveable')


class ReferenceTransfers(unittest.TestCase):
    def setUp(self):
        RNA.data.node_groups.clear()
        file_actions.clear_drag()
        RUNTIME._epoch = 0
        RUNTIME.interaction_busy = lambda _tree: False
        self.source = RNA.data.node_groups.new('Source', model.TREE)
        self.target = RNA.data.node_groups.new('Target', model.TREE)
        self.context = SimpleNamespace(tree=self.source)
        self.cards = []
        for index, position in enumerate(((300, 120), (-300, -180))):
            parent = self.source.nodes.new(model.FRAME)
            parent.location = position
            node = self.source.nodes.new(model.FILE)
            node.parent, node.location, node.select = parent, (40, -50), True
            node.filepath = f'D:\\owned-fixture\\source-{index}.txt'
            self.cards.append(node)

    def prepare(self):
        operator = file_actions.WM_OT_blui_canvas_drag_prepare()
        operator.filepath = self.cards[0].filepath
        self.assertEqual(operator.execute(self.context), {'FINISHED'})
        return [node.filepath for node in self.cards]

    def test_cross_board_copy_preserves_absolute_spacing_and_source_frames(self):
        paths = self.prepare()
        with mock.patch.object(file_actions.os, 'startfile', side_effect=AssertionError('No disk/shell action')):
            self.assertTrue(file_actions.drop_references(self.target, paths, (100, 200), copy=True))
        self.assertEqual([node.location for node in self.target.nodes], [[100, 200], [-500, -100]])
        self.assertEqual([node.location for node in self.cards], [[40, -50], [40, -50]])
        self.assertTrue(all(node.parent for node in self.cards))
        self.assertTrue(all(node.parent is None for node in self.target.nodes))

    def test_cross_board_move_removes_only_original_card_references(self):
        paths = self.prepare()
        self.assertTrue(file_actions.drop_references(self.target, paths, (100, 200)))
        self.assertEqual([node.filepath for node in self.target.nodes], paths)
        self.assertEqual([node.bl_idname for node in self.source.nodes], [model.FRAME, model.FRAME])

    def test_same_board_movement_converts_global_drop_to_parent_local_coordinates(self):
        paths = self.prepare()
        self.assertTrue(file_actions.drop_references(self.source, paths, (100, 200)))
        self.assertEqual([file_actions.absolute_location(node) for node in self.cards], [[100, 200], [-500, -100]])
        self.assertTrue(all(node.parent for node in self.cards))

    def test_ctrl_copy_on_same_board_allocates_new_references_not_moves_originals(self):
        paths = self.prepare()
        self.assertTrue(file_actions.drop_references(self.source, paths, (100, 200), copy=True))
        nodes = [node for node in self.source.nodes if node.bl_idname == model.FILE]
        self.assertEqual(len(nodes), 4)
        self.assertEqual([node.location for node in self.cards], [[40, -50], [40, -50]])
        self.assertEqual([node.location for node in nodes[2:]], [[100, 200], [-500, -100]])

    def test_stale_changed_source_and_undo_epoch_never_remove_source(self):
        paths = self.prepare()
        self.cards[0].label = 'Edited after drag'
        with self.assertRaises(ValueError):
            file_actions.drop_references(self.target, paths, (0, 0))
        self.assertEqual(len(self.target.nodes), 0)
        self.assertTrue(all(node in self.source.nodes for node in self.cards))
        paths = self.prepare()
        RUNTIME._epoch += 1
        with self.assertRaises(ValueError):
            file_actions.drop_references(self.target, paths, (0, 0))
        self.assertEqual(len(self.target.nodes), 0)

    def test_native_modal_blocks_cross_board_mutation(self):
        paths = self.prepare()
        RUNTIME.interaction_busy = lambda _tree: True
        with self.assertRaises(ValueError):
            file_actions.drop_references(self.target, paths, (0, 0))
        self.assertFalse(self.target.nodes)
        self.assertTrue(all(node in self.source.nodes for node in self.cards))

    def test_unselected_group_does_not_leak_hidden_frame_selection_into_file_actions(self):
        child = RNA.data.node_groups.new('Hidden group', model.TREE)
        frame = child.nodes.new(model.FRAME)
        frame.select = True
        hidden = child.nodes.new(model.FILE)
        hidden.filepath, hidden.parent = 'D:\\fixture\\must-not-be-recycled.txt', frame
        group = self.source.nodes.new(model.GROUP)
        group.node_tree, group.select = child, False
        self.cards[1].select = False
        self.assertEqual(file_actions.selected_paths(self.context), [self.cards[0].filepath],
                         'An unselected group leaked a hidden selected frame into file operations')

    def test_explicitly_selected_native_group_includes_its_actual_file_references(self):
        child = RNA.data.node_groups.new('Selected group', model.TREE)
        hidden = child.nodes.new(model.FILE)
        hidden.filepath = 'D:\\fixture\\group-selected.txt'
        group = self.source.nodes.new(model.GROUP)
        group.node_tree, group.select = child, True
        for card in self.cards:
            card.select = False
        self.assertEqual(file_actions.selected_paths(self.context), [hidden.filepath])

    def test_second_allocation_failure_rolls_back_staged_destination(self):
        paths = self.prepare()
        new = self.target.nodes.new
        def failing_new(kind):
            if self.target.nodes:
                raise MemoryError('Owned second allocation failure')
            return new(kind)
        with mock.patch.object(self.target.nodes, 'new', side_effect=failing_new):
            with self.assertRaises(MemoryError):
                file_actions.drop_references(self.target, paths, (0, 0))
        self.assertFalse(self.target.nodes)
        self.assertTrue(all(node in self.source.nodes for node in self.cards))

    def test_first_property_failure_removes_partially_allocated_destination(self):
        paths = self.prepare()
        original = Node.__setattr__
        def failing_property(node, key, value):
            if getattr(node, 'id_data', None) is self.target and key == 'filepath' and value:
                raise RuntimeError('Owned RNA property allocation failure')
            original(node, key, value)
        with mock.patch.object(Node, '__setattr__', failing_property):
            with self.assertRaises(RuntimeError):
                file_actions.drop_references(self.target, paths, (0, 0))
        self.assertFalse(self.target.nodes, 'Partially created target icon leaked after RNA assignment failed')
        self.assertTrue(all(node in self.source.nodes for node in self.cards))


if __name__ == '__main__':
    unittest.main(verbosity=2)
