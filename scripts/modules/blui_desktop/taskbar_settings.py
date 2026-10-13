# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure taskbar preference schema; load/save are isolated-worker-only I/O."""
import json
import os
from pathlib import Path
import time
from . import model

VERSION = 1
MAX_BYTES = 4096
MAX_REVISION = (1 << 53) - 1
HEIGHT_MIN, HEIGHT_MAX = 32, 160
ICON_MIN, ICON_MAX = 16, 64


def defaults():
    return {'version': VERSION, 'revision': 0, 'height': 56, 'icon_size': 32}


def validate(value):
    """Canonicalize dimensions: enlarged icons always keep sixteen pixels of room."""
    if not isinstance(value, dict) or set(value) != set(defaults()):
        raise ValueError('Invalid taskbar preferences')
    if type(value['version']) is not int or value['version'] != VERSION:
        raise ValueError('Unsupported taskbar preferences')
    if type(value['revision']) is not int or not 0 <= value['revision'] <= MAX_REVISION:
        raise ValueError('Invalid taskbar preference revision')
    if type(value['height']) is not int or not HEIGHT_MIN <= value['height'] <= HEIGHT_MAX:
        raise ValueError('Invalid taskbar height')
    if type(value['icon_size']) is not int or not ICON_MIN <= value['icon_size'] <= ICON_MAX:
        raise ValueError('Invalid taskbar icon size')
    return {**value, 'height': max(value['height'], value['icon_size'] + 16)}


def changed(current, *, height=None, icon_size=None):
    current = validate(current)
    value = {**current, 'height': current['height'] if height is None else height,
             'icon_size': current['icon_size'] if icon_size is None else icon_size}
    value = validate(value)
    if value != current:
        value['revision'] += 1
    return validate(value)


def _path(directory):
    if (not isinstance(directory, str) or not directory or len(directory) > 32768 or
            '\x00' in directory or not os.path.isabs(directory)):
        raise ValueError('Invalid taskbar configuration directory')
    return Path(directory) / 'taskbar-settings.json'


def _read(path):
    with path.open('rb') as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Taskbar preferences are too large')
    return validate(json.loads(data.decode('utf-8')))


def load(directory):
    """Worker-only: recover a valid backup, then fall back to safe defaults."""
    target = _path(directory)
    for candidate in (target, target.with_suffix('.bak')):
        try:
            return _read(candidate)
        except (OSError, ValueError, UnicodeError):
            pass
    return defaults()


def save(directory, value):
    """Worker-only: same atomic fsync/replace and OS lock as desktop layouts."""
    value, target = validate(value), _path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    with model._save_lock(target):
        current = load(directory)
        if current['revision'] > value['revision'] or (
                current['revision'] == value['revision'] and current != value):
            raise ValueError('Taskbar preferences changed; reload the settings')
        try:
            previous = _read(target)
        except (OSError, ValueError, UnicodeError):
            previous = None
        if previous is not None:
            model._publish(target.with_suffix('.bak'), json.dumps(previous).encode('utf-8'))
        model._publish(target, json.dumps(value, ensure_ascii=False).encode('utf-8'))
    return True


# Main-thread adapter: bounded memory operations; all filesystem work remains in
# the existing isolated Job worker. Import client only when servicing the timer.
_current = defaults()
_directory = ''
_loaded = False
_dirty = False
_job = None
_action = ''
_submitted = None
_retry = 0.0
_error = ''


def values():
    return dict(_current)


snapshot = values


def error():
    return _error


def configure(*, height=None, icon_size=None):
    global _current, _dirty, _error
    updated = changed(_current, height=height, icon_size=icon_size)
    if updated != _current:
        _current, _dirty, _error = updated, True, ''
    return values()


def shutdown():
    global _job, _action, _submitted
    if _job is not None:
        _job.close()
    _job, _action, _submitted = None, '', None


def service_tick(directory, *, clock=time.monotonic, job_factory=None):
    """Consume/load/save nonblocking isolated jobs, coalescing successive UI edits."""
    global _current, _directory, _loaded, _dirty, _job, _action, _submitted, _retry, _error
    _path(directory)  # Validate only; creating a Path does not touch the filesystem.
    now = clock()
    if _directory != directory:
        shutdown()
        _directory, _loaded, _retry = directory, False, 0.0
    if _job is not None and _job.done():
        action, submitted, reply = _action, _submitted, _job.reply
        shutdown()
        try:
            if not isinstance(reply, dict) or reply.get('ok') is not True:
                raise ValueError(str(reply.get('error', 'Taskbar preferences unavailable'))
                                 if isinstance(reply, dict) else 'Taskbar preferences unavailable')
            if action == 'taskbar_settings_load':
                loaded = validate(reply.get('value'))
                _current = changed(loaded, height=_current['height'], icon_size=_current['icon_size']) if _dirty else loaded
                _loaded = True
            elif reply.get('value') is True:
                _dirty = _current != submitted
            else:
                raise ValueError('Invalid taskbar preference save result')
            _error = ''
        except (ValueError, TypeError) as exc:
            _error, _loaded, _retry = str(exc)[:1024], False, now + 3
    if _job is not None or now < _retry or (_loaded and not _dirty):
        return values()
    if job_factory is None:
        from .client import Job
        job_factory = Job
    try:
        if not _loaded:
            _action, _submitted = 'taskbar_settings_load', None
            _job = job_factory(_action, directory, timeout=6)
        else:
            _action, _submitted = 'taskbar_settings_save', values()
            _job = job_factory(_action, directory, _submitted, timeout=6)
    except (RuntimeError, ValueError, OSError) as exc:
        _job, _action, _submitted = None, '', None
        _error, _retry = str(exc)[:1024], now + 3
    return values()
