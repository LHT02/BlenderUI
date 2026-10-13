# SPDX-License-Identifier: GPL-2.0-or-later
"""Portable multi-canvas snapshots and reference-only transfers; no bpy or shell APIs.

``save`` and ``load`` are worker-only filesystem operations. Everything else is
bounded, pure-memory validation suitable for the main-thread RNA adapter.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import uuid

from . import model

VERSION = 2
MAX_BOARDS = 32
MAX_REVISION = (1 << 53) - 1
MAX_BYTES = model.MAX_BYTES


def uuid_key(value):
    return isinstance(value, str) and len(value) == 32 and all(
        char in '0123456789abcdef' for char in value)


def revision(value):
    if type(value) is not int or not 0 <= value <= MAX_REVISION:
        raise ValueError('Invalid desktop revision')
    return value


def _text(value, limit=32768):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ValueError('Invalid desktop text')
    return value


def _position(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(
            type(item) in (int, float) and math.isfinite(item) and abs(item) <= 1e7
            for item in value):
        raise ValueError('Invalid desktop position')
    return list(value)


def with_node_ids(layout):
    """Assign persistent IDs once when taking ownership of a new/legacy layout."""
    result = deepcopy(layout)
    for row in result.get('nodes', []):
        row.setdefault('id', uuid.uuid4().hex)
    return result


def _layout(value):
    clean = model.validate(value)
    seen = set()
    for raw, row in zip(value['nodes'], clean['nodes']):
        key = raw.get('id')
        if not uuid_key(key) or key in seen:
            raise ValueError('Invalid or duplicate desktop card identity')
        seen.add(key)
        row['id'] = key
    return clean


def new_board(name='Desktop', layout=None):
    return {'id': uuid.uuid4().hex, 'name': _text(name, 255), 'revision': 0,
            'layout': _layout(with_node_ids(layout or {
                'version': 1, 'directory': '', 'nodes': []})),
            'monitor': '', 'view': {'center': [0, 0], 'zoom': 1.0}}


def new_collection(name='Desktop', layout=None):
    board = new_board(name, layout)
    return {'version': VERSION, 'id': uuid.uuid4().hex, 'revision': 0,
            'active': board['id'], 'boards': [board]}


def validate(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != VERSION:
        raise ValueError('Unsupported desktop collection')
    if not uuid_key(value.get('id')):
        raise ValueError('Invalid desktop collection identity')
    rows = value.get('boards')
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_BOARDS:
        raise ValueError('Invalid desktop count')
    clean, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not uuid_key(row.get('id')) or row['id'] in seen:
            raise ValueError('Invalid or duplicate desktop identity')
        seen.add(row['id'])
        view = row.get('view', {'center': [0, 0], 'zoom': 1.0})
        zoom = view.get('zoom') if isinstance(view, dict) else None
        if type(zoom) not in (int, float) or not math.isfinite(zoom) or not .01 <= zoom <= 100:
            raise ValueError('Invalid desktop zoom')
        clean.append({'id': row['id'], 'name': _text(row.get('name', ''), 255),
                      'revision': revision(row.get('revision')),
                      'layout': _layout(row.get('layout')), 'monitor': _text(row.get('monitor', ''), 255),
                      'view': {'center': _position(view.get('center')), 'zoom': float(zoom)}})
    if value.get('active') not in seen:
        raise ValueError('Active desktop no longer exists')
    return {'version': VERSION, 'id': value['id'], 'revision': revision(value.get('revision')),
            'active': value['active'], 'boards': clean}


def encoded(value):
    data = json.dumps(validate(value), ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(data) > MAX_BYTES:
        raise ValueError('Desktop collection is too large')
    return data


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def _read(target):
    with target.open('rb') as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Desktop collection is too large')
    return validate(json.loads(data.decode('utf-8')))


def _valid_copies(target):
    copies = []
    for path in (target, target.with_suffix('.bak')):
        try:
            copies.append((_read(path), path == target))
        except (OSError, ValueError, UnicodeError, RecursionError):
            pass
    if len(copies) == 2 and copies[0][0]['id'] != copies[1][0]['id']:
        # Never pick a newer-looking backup from an unrelated collection.
        return copies[:1]
    return sorted(copies, key=lambda item: (item[0]['revision'], item[1]), reverse=True)


def load(path):
    """Recover all desktops together, selecting the newest complete valid snapshot."""
    copies = _valid_copies(Path(path))
    if not copies:
        raise ValueError('No valid desktop snapshot or backup is available')
    return copies[0][0]


def save(path, payload):
    """Atomic all-board write, serialized across helpers and monotonic by revision."""
    payload = validate(payload)
    data = encoded(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with model._save_lock(target):
        copies = _valid_copies(target)
        previous = copies[0][0] if copies else None
        if previous:
            if previous['id'] != payload['id']:
                raise ValueError('A different desktop collection already owns this path')
            if payload['revision'] < previous['revision']:
                raise ValueError('An older desktop revision cannot replace a newer snapshot')
            if payload['revision'] == previous['revision'] and data != encoded(previous):
                raise ValueError('Conflicting desktop changes have the same revision')
            previous_boards = {row['id']: row for row in previous['boards']}
            for row in payload['boards']:
                prior = previous_boards.get(row['id'])
                if prior and row['revision'] < prior['revision']:
                    raise ValueError('An older canvas revision cannot replace a newer layout')
            if payload['revision'] > previous['revision']:
                model._publish(target.with_suffix('.bak'), encoded(previous))
        model._publish(target, data)
        # A first-save crash must also have a valid backup, not wait for the next save.
        # Also repair a first backup creation interrupted after the current file
        # was published: an idempotent retry must not leave recovery missing.
        if not any(not is_current for _snapshot, is_current in copies):
            model._publish(target.with_suffix('.bak'), encoded(previous) if previous else data)
    return {'id': payload['id'], 'revision': payload['revision'], 'path': str(target)}


def prepare_transfer(collection, source_id, target_id, card_ids, *, copy=False,
                     origin=(0, 0), epoch=0):
    """Capture identities before asynchronous UI work; no source removal occurs here."""
    collection = validate(collection)
    if type(copy) is not bool or type(epoch) is not int or epoch < 0:
        raise ValueError('Invalid desktop transfer')
    if source_id == target_id:
        raise ValueError('Choose a different desktop')
    if not isinstance(card_ids, (list, tuple)) or not card_ids or len(card_ids) > model.LIMIT:
        raise ValueError('Invalid desktop card selection')
    if not all(uuid_key(key) for key in card_ids):
        raise ValueError('Invalid desktop card identity')
    keys = set(card_ids)
    if len(keys) != len(card_ids):
        raise ValueError('Invalid desktop card identity')
    by_id = {row['id']: row for row in collection['boards']}
    if source_id not in by_id or target_id not in by_id:
        raise ValueError('Desktop no longer exists')
    source, target = by_id[source_id], by_id[target_id]
    selected = [deepcopy(row) for row in source['layout']['nodes'] if row['id'] in keys]
    if len(selected) != len(keys):
        raise ValueError('Desktop card changed before dragging')
    if len(target['layout']['nodes']) + len(selected) > model.LIMIT:
        raise ValueError('Destination desktop contains too many cards')
    return {'id': uuid.uuid4().hex, 'collection': collection['id'], 'epoch': epoch,
            'source': source_id, 'target': target_id, 'source_revision': source['revision'],
            'target_revision': target['revision'], 'source_hash': fingerprint_layout(source['layout']),
            'target_hash': fingerprint_layout(target['layout']), 'cards': selected,
            'copy': copy, 'origin': _position(origin)}


def fingerprint_layout(layout):
    data = json.dumps(_layout(layout), sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def commit_transfer(collection, prepared, *, epoch=0):
    """Return one complete replacement collection or fail without mutating either board.

    The RNA adapter must stage destination nodes successfully before deleting source
    references, and apply this result in one undoable operation. Files on disk are
    never moved, copied, opened, or deleted by this transfer service.
    """
    result = validate(collection)
    if (not isinstance(prepared, dict) or not uuid_key(prepared.get('id')) or
            prepared.get('collection') != result['id'] or prepared.get('epoch') != epoch):
        raise ValueError('Desktop drag expired; nothing was moved')
    if not uuid_key(prepared.get('source')) or not uuid_key(prepared.get('target')):
        raise ValueError('Invalid desktop drag destination')
    by_id = {row['id']: row for row in result['boards']}
    source, target = by_id.get(prepared.get('source')), by_id.get(prepared.get('target'))
    if (not source or not target or source is target or
            source['revision'] != prepared.get('source_revision') or
            target['revision'] != prepared.get('target_revision') or
            fingerprint_layout(source['layout']) != prepared.get('source_hash') or
            fingerprint_layout(target['layout']) != prepared.get('target_hash')):
        raise ValueError('Desktop changed during dragging; nothing was moved')
    cards = prepared.get('cards')
    if not isinstance(cards, list) or not cards or type(prepared.get('copy')) is not bool:
        raise ValueError('Invalid desktop drag payload')
    # Do not trust serialized card content; recover exact rows from the live snapshot.
    if not all(isinstance(row, dict) and uuid_key(row.get('id')) for row in cards):
        raise ValueError('Invalid desktop drag selection')
    keys = {row['id'] for row in cards}
    selected = [deepcopy(row) for row in source['layout']['nodes'] if row['id'] in keys]
    if len(keys) != len(cards) or len(selected) != len(cards):
        raise ValueError('Desktop drag selection changed')
    if len(target['layout']['nodes']) + len(selected) > model.LIMIT:
        raise ValueError('Destination desktop contains too many cards')
    origin = _position(prepared.get('origin'))
    anchor = selected[0]['location']
    target_keys = {row['id'] for row in target['layout']['nodes']}
    for row in selected:
        if prepared['copy'] or row['id'] in target_keys:
            row['id'] = uuid.uuid4().hex
        row['location'] = [origin[0] + row['location'][0] - anchor[0],
                           origin[1] + row['location'][1] - anchor[1]]
    target['layout']['nodes'].extend(selected)
    target['revision'] = revision(target['revision'] + 1)
    if not prepared['copy']:
        source['layout']['nodes'] = [row for row in source['layout']['nodes'] if row['id'] not in keys]
        source['revision'] = revision(source['revision'] + 1)
    result['revision'] = revision(result['revision'] + 1)
    result['active'] = target['id']
    return validate(result)


def display_bindings(collection, displays):
    """Match connected displays without deleting layouts belonging to unplugged screens.

    DeviceName is a best-effort Windows topology identity, not a permanent
    hardware serial number. Users may explicitly reassign an unmatched saved
    canvas after a driver renames a display; no guesses overwrite its layout.
    """
    from . import monitors
    collection, displays = validate(collection), monitors.validate(displays)
    by_device = {}
    for board in collection['boards']:
        if board['monitor']:
            by_device.setdefault(board['monitor'], []).append(board['id'])
    attached = []
    connected = {row['device'] for row in displays['monitors']}
    for row in displays['monitors']:
        attached.append({**deepcopy(row), 'boards': by_device.get(row['device'], [])})
    detached = [board['id'] for board in collection['boards']
                if board['monitor'] and board['monitor'] not in connected]
    unassigned = [board['id'] for board in collection['boards'] if not board['monitor']]
    return {'attached': attached, 'detached': detached, 'unassigned': unassigned}
