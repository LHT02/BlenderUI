# SPDX-License-Identifier: GPL-2.0-or-later
"""Multi-monitor board ownership and periodic crash-safe snapshot orchestration."""
import json
import os
import uuid
import bpy
from . import autosave, boards, client, model, serialization
from blui_explorer.localization import iface

_collection = None
_restore = None
_loading = False
_loaded = False
_expected = {}
_snapshot_error = ''
_scheduler = autosave.Scheduler(client.Job)
disable_for_tests = False


def storage_directory():
    return os.environ.get('BLUI_DESKTOP_CONFIG') or bpy.utils.user_resource('CONFIG', path='blui_desktop')


def storage_path():
    return os.path.join(storage_directory(), 'displays.json')


def roots():
    return [tree for tree in bpy.data.node_groups if tree.bl_idname == model.TREE and tree.board_id]


def by_id(key):
    return next((tree for tree in roots() if tree.board_id == key), None)


def attach(tree, name='Desktop', monitor=''):
    tree.board_id = tree.board_id or uuid.uuid4().hex
    tree.layout_key = tree.board_id
    tree.board_name, tree.monitor = name, monitor


def begin(runtime):
    global _loading, _expected
    if disable_for_tests or _loaded or _loading or _restore is not None:
        return
    _expected = {tree.board_id: runtime.fingerprint(tree) for tree in roots()}
    runtime.submit('board_load', None, storage_path())
    _loading = True


def receive(value):
    global _restore, _loading
    _restore = boards.validate(value)
    _loading = False


def missing():
    global _loaded, _loading
    _loaded, _loading = True, False


def collection():
    global _collection
    if _collection is None:
        _collection = {'version': 2, 'id': uuid.uuid4().hex, 'revision': 0, 'active': '', 'boards': []}
    changed = False
    for tree in roots():
        layout = serialization.snapshot(tree)
        row = next((row for row in _collection['boards'] if row['id'] == tree.board_id), None)
        if row is None:
            row = boards.new_board(tree.board_name, layout)
            row['id'] = tree.board_id
            _collection['boards'].append(row)
            changed = True
        if row['layout'] != layout or row['name'] != tree.board_name or row['monitor'] != tree.monitor:
            row.update(layout=layout, name=tree.board_name, monitor=tree.monitor,
                       revision=row['revision'] + 1)
            changed = True
    if not _collection['boards']:
        return None
    if _collection['active'] not in {row['id'] for row in _collection['boards']}:
        _collection['active'] = _collection['boards'][0]['id']
        changed = True
    if changed:
        _collection['revision'] += 1
    return boards.validate(_collection)


def tick(runtime):
    global _collection, _restore, _loaded, _snapshot_error
    if disable_for_tests or runtime.interaction_busy(None):
        return
    if _restore is not None:
        value, _restore = _restore, None
        current = roots()
        # Initial empty window adopts the active saved board. Never replace an edited board.
        empty = next((tree for tree in current if not tree.nodes), None)
        try:
            for row in value['boards']:
                tree = by_id(row['id'])
                if tree is None and row['id'] == value['active'] and empty is not None:
                    tree, empty = empty, None
                if tree is None:
                    tree = bpy.data.node_groups.new(row['name'] or 'Desktop', model.TREE)
                if tree.board_id in _expected and runtime.fingerprint(tree) != _expected[tree.board_id]:
                    tree.service_status = iface('Canvas changed; request restoration again')
                    continue
                if tree.nodes and tree.board_id != row['id']:
                    continue
                serialization.apply(tree, row['layout'])
                tree.use_fake_user = True
                attach(tree, row['name'], row['monitor'])
                tree.board_id, tree.layout_key = row['id'], row['id']
                tree.service_status = iface('Canvas layout restored')
            _collection, _loaded = value, True
            _scheduler.observe(storage_path(), value, epoch=runtime._epoch, already_saved=True)
        except (RuntimeError, ValueError, ReferenceError) as exc:
            _loaded = True
            for tree in roots():
                tree.service_status = str(exc)
    if not _loaded:
        return
    # collection() replaces complete layouts, but updates board records in place.
    # Roll back those records if any board fails before the collection revision advances.
    previous = None if _collection is None else {
        **_collection, 'boards': [dict(row) for row in _collection['boards']]}
    try:
        value = collection()
        _snapshot_error = ''
        if value:
            _scheduler.observe(storage_path(), value, epoch=runtime._epoch)
            event = _scheduler.tick()
            if event:
                for tree in roots():
                    tree.service_status = iface('Canvas layout saved') if event['saved'] else event['error']
    except (RuntimeError, ValueError, OSError, ReferenceError) as exc:
        _collection = previous
        _snapshot_error = str(exc)
        for tree in roots():
            tree.service_status = _snapshot_error


def save_now(runtime):
    value = collection()
    if not value or not _loaded:
        raise RuntimeError(iface('Loading...'))
    _scheduler.observe(storage_path(), value, epoch=runtime._epoch)
    return _scheduler.tick(force=True)


def reset(epoch):
    global _restore, _loading, _expected, _snapshot_error
    _restore, _loading = None, False
    _expected.clear()
    _snapshot_error = ''
    _scheduler.reset(epoch=epoch)


def autosave_status():
    return _snapshot_error or _scheduler.error or (iface('Unsaved layout changes') if _scheduler.dirty else iface('Canvas layout saved'))
