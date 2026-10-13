# SPDX-License-Identifier: GPL-2.0-or-later
"""Main-thread, memory-only Start-menu facade; slow work uses disposable desktop jobs."""
import copy
import time
from . import client, start_menu_model as schema

_directory = ''
_rows = []
_preferences = schema.empty_state()
_jobs = []
_loaded = False
_truncated = False
_error = ''
_serial = 0
_generation = 0
_dirty = False
_retry_at = 0.0


def snapshot():
    """Only Python memory is read from draw callbacks."""
    return {'loaded': _loaded, 'loading': any(action == 'start_index' for _, action, _, _ in _jobs),
            'rows': _rows, 'pins': list(_preferences['pins']), 'recent': list(_preferences['recent']),
            'truncated': _truncated, 'error': _error, 'revision': _preferences['revision']}


def ensure(directory, *, refresh=False):
    global _directory, _error
    if directory != _directory:
        close()
        _directory = directory
    if any(action == 'start_index' for _, action, _, _ in _jobs) or (_loaded and not refresh):
        return
    _jobs.append((client.Job('start_index', directory, timeout=12), 'start_index', _serial, _generation))
    _error = ''


def _changed():
    global _serial, _dirty, _retry_at
    _preferences['revision'] += 1
    if _preferences['revision'] >= 1 << 63:
        raise ValueError('Start menu preferences revision limit reached')
    _serial += 1
    _dirty, _retry_at = True, time.monotonic() + .15


def pin(identity):
    identity = schema.key(identity)
    if not _loaded or not any(row['id'] == identity for row in _rows):
        raise ValueError('The program is no longer indexed; refresh the menu')
    pins = _preferences['pins']
    if identity in pins:
        pins.remove(identity)
    elif len(pins) < schema.MAX_PINS:
        pins.append(identity)
    else:
        raise ValueError('Start menu pinned program limit reached')
    _changed()


def launch(identity):
    identity = schema.key(identity)
    row = next((row for row in _rows if row['id'] == identity), None)
    if not _loaded or row is None:
        raise ValueError('The program is no longer indexed; refresh the menu')
    # One click starts one process. Repeated clicks while its checked launch is pending do not duplicate it.
    if any(action == 'start_launch' for _, action, _, _ in _jobs):
        raise RuntimeError('A program launch is still pending')
    _jobs.append((client.Job('start_launch', row, timeout=8), 'start_launch', identity, _generation))


def system_action(action):
    if not isinstance(action, str) or action not in schema.SYSTEM_ACTIONS:
        raise ValueError('Unsupported Start menu system action')
    if any(kind == 'start_system' for _, kind, _, _ in _jobs):
        raise RuntimeError('A system action is still pending')
    _jobs.append((client.Job('start_system', action, timeout=8), 'start_system', action, _generation))


def open_location(identity):
    identity = schema.key(identity)
    row = next((row for row in _rows if row['id'] == identity), None)
    if not _loaded or row is None:
        raise ValueError('The program is no longer indexed; refresh the menu')
    if any(action == 'start_location' for _, action, _, _ in _jobs):
        raise RuntimeError('A system action is still pending')
    _jobs.append((client.Job('start_location', row, timeout=8), 'start_location', identity, _generation))


def tick():
    """Consume validated replies without RNA pointers, filesystem access or process waits."""
    global _rows, _preferences, _loaded, _truncated, _error, _dirty, _retry_at
    changed = False
    for item in list(_jobs):
        job, action, token, generation = item
        if not job.done():
            continue
        _jobs.remove(item)
        try:
            value = job.result()
            if generation != _generation:
                continue
            if action == 'start_index':
                value = schema.validate_index(value)
                _rows, _loaded, _truncated = value['rows'], True, value['truncated']
                # A refresh finishing after a user pinned an app must not rewind those local changes.
                if token == _serial and not _dirty and value['revision'] >= _preferences['revision']:
                    _preferences = schema.state(value)
                _error = value['errors'][0] if value['errors'] else ''
            elif action == 'start_launch':
                _preferences['recent'] = ([token] + [key for key in _preferences['recent'] if key != token])[:schema.MAX_RECENT]
                _changed()
                _error = ''
            elif action == 'start_state':
                _dirty = token != _serial
                _error = ''
            else:
                _error = ''
            changed = True
        except (RuntimeError, ValueError, OSError) as error:
            if generation != _generation:
                continue
            _error = str(error)
            if action == 'start_state':
                # Another BLUI process may own a newer configuration. Do not repeatedly overwrite it.
                _dirty = not ('preferences changed' in _error or 'Conflicting' in _error)
                _retry_at = time.monotonic() + 2
            changed = True
    if (_directory and _dirty and _loaded and time.monotonic() >= _retry_at and
            not any(action == 'start_state' for _, action, _, _ in _jobs)):
        try:
            _jobs.append((client.Job('start_state', _directory, copy.deepcopy(_preferences)),
                          'start_state', _serial, _generation))
        except RuntimeError:
            _retry_at = time.monotonic() + .5
    return changed


def busy():
    return bool(_jobs or _dirty)


def close():
    global _directory, _rows, _preferences, _loaded, _truncated, _error, _serial, _generation, _dirty
    for job, _action, _token, _generation_at_submit in _jobs:
        job.close()
    _jobs.clear()
    _generation += 1
    _directory, _rows, _preferences = '', [], schema.empty_state()
    _loaded, _truncated, _error, _serial, _dirty = False, False, '', 0, False
