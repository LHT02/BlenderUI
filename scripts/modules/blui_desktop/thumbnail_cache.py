# SPDX-License-Identifier: GPL-2.0-or-later
"""Main-thread RAM-only thumbnail cache. Path probing/decoding happens in disposable helpers."""
import base64
import hashlib
import time
from collections import OrderedDict
import bpy.utils.previews
from . import thumbnails

_previews = None
_entries = OrderedDict()
_queued = OrderedDict()
_inflight = set()
_sources = {}
_unique = OrderedDict()
MAX_ENTRIES = 1000
MAX_PIXELS = 8 * 1024 * 1024
REFRESH_SECONDS = 60.0
FAIL_SECONDS = 120.0


def value(path, folder=False):
    if not thumbnails.candidate(path, folder):
        return 0
    now = time.monotonic()
    entry = _entries.get(path)
    if entry is None or now >= entry[1]:
        if path not in _inflight:
            _queued.setdefault(path, None)
            while len(_queued) > MAX_ENTRIES:
                _queued.popitem(last=False)
    if entry is not None:
        _entries.move_to_end(path)
        return entry[0]
    return 0


def pending():
    batch = []
    while _queued and len(batch) < thumbnails.BATCH:
        path, _unused = _queued.popitem(last=False)
        _inflight.add(path)
        batch.append(path)
    return batch


def retry(paths):
    """An admission failure made no request; retain work without adding a failure cooldown."""
    for path in paths:
        _inflight.discard(path)
        if thumbnails.candidate(path):
            _queued.setdefault(path, None)


def fail(paths):
    """Timeout/crash never leaves a permanent loading slot. Keep an old preview if available."""
    due = time.monotonic() + FAIL_SECONDS
    for path in paths:
        _inflight.discard(path)
        _queued.pop(path, None)
        if thumbnails.valid_path(path):
            _entries[path] = (_entries.get(path, (0, 0))[0], due)
    _trim()


def _trim():
    while len(_entries) > MAX_ENTRIES:
        path, _entry = _entries.popitem(last=False)
        _sources.pop(path, None)
    used = set(_sources.values())
    for digest in list(_unique):
        if digest not in used:
            _unique.pop(digest)
            if _previews is not None:
                del _previews[digest]
    while sum(_unique.values()) > MAX_PIXELS:
        digest, _pixels = _unique.popitem(last=False)
        for path in [path for path, value in _sources.items() if value == digest]:
            _sources.pop(path, None)
            _entries.pop(path, None)
        if _previews is not None:
            del _previews[digest]


def apply(rows):
    global _previews
    thumbnails.validate_pixels(rows)
    if _previews is None and any(row['width'] for row in rows):
        _previews = bpy.utils.previews.new()
    now = time.monotonic()
    for row in rows:
        path, width, height = row['path'], row['width'], row['height']
        _inflight.discard(path)
        _queued.pop(path, None)
        if not width:
            _sources.pop(path, None)
            _entries[path] = (0, now + FAIL_SECONDS)
            continue
        pixels = base64.b64decode(row['rgba'], validate=True)
        stride = width * 4
        # Exactly one top-down -> bottom-up conversion at the Blender PreviewImage boundary.
        flipped = b''.join(pixels[y * stride:(y + 1) * stride] for y in range(height - 1, -1, -1))
        digest = hashlib.sha256(width.to_bytes(4, 'little') + height.to_bytes(4, 'little') + flipped).hexdigest()
        if digest in _unique:
            preview = _previews[digest]
            _unique.move_to_end(digest)
        else:
            preview = _previews.new(digest)
            preview.image_size = (width, height)
            preview.image_pixels_float = [component / 255.0 for component in flipped]
            _unique[digest] = width * height
        _sources[path] = digest
        _entries[path] = (preview.icon_id, now + REFRESH_SECONDS)
        _entries.move_to_end(path)
    _trim()


def cancel_pending():
    """Undo/load cancels jobs, but keeps useful RAM thumbnails and makes abandoned work retryable."""
    _inflight.clear()
    _queued.clear()


def close():
    global _previews
    cancel_pending()
    _entries.clear()
    _sources.clear()
    _unique.clear()
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
