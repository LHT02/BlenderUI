# SPDX-License-Identifier: GPL-2.0-or-later
"""Main-thread preview cache. Extraction and all slow path queries stay in helpers."""
import base64
import hashlib
from collections import OrderedDict
import bpy.utils.previews

_previews = None
_icons = OrderedDict()
_queued = set()
_sources = {}
_unique = OrderedDict()
MAX_ICONS = 1100
MAX_PIXELS = 16 * 1024 * 1024


def value(path):
    if not path or '\x00' in path or len(path) > 32768:
        return 0
    entry = _icons.get(path)
    if entry is None:
        _queued.add(path)
        return 0
    _icons.move_to_end(path)
    return entry


def pending():
    batch = list(_queued)[:4]
    _queued.difference_update(batch)
    return batch


def retry(paths):
    """Admission made no request; an uncached icon must remain eligible for a later batch."""
    for path in paths:
        if path and '\x00' not in path and len(path) <= 32768 and path not in _icons:
            _queued.add(path)


def apply(rows):
    global _previews
    if _previews is None:
        _previews = bpy.utils.previews.new()
    for row in rows:
        path, width, height = row['path'], row['width'], row['height']
        if path in _icons:
            continue
        if not width or not height:
            _icons[path] = 0
            continue
        pixels = base64.b64decode(row['rgba'], validate=True)
        if len(pixels) != width * height * 4:
            raise ValueError('Invalid desktop icon pixels')
        # Native extractor is top-down; PreviewImage follows Blender's bottom-up storage.
        stride = width * 4
        flipped = b''.join(pixels[y * stride:(y + 1) * stride] for y in range(height - 1, -1, -1))
        digest = hashlib.sha256(width.to_bytes(4, 'little') + height.to_bytes(4, 'little') + flipped).hexdigest()
        if digest in _unique:
            preview = _previews[digest]
            _unique.move_to_end(digest)
        else:
            preview = _previews.new(digest)
            preview.image_size = (width, height)
            floats = [component / 255.0 for component in flipped]
            preview.image_pixels_float = floats
            # Operator/menu buttons use ICON_SIZE_ICON, not the large template_icon
            # slot. A valid icon_id alone otherwise paints an empty application button.
            preview.icon_size = (width, height)
            preview.icon_pixels_float = floats
            _unique[digest] = width * height * 2
        _sources[path] = digest
        _icons[path] = preview.icon_id
    while len(_icons) > MAX_ICONS:
        key, icon = _icons.popitem(last=False)
        _sources.pop(key, None)
    while sum(_unique.values()) > MAX_PIXELS:
        digest, _pixels = _unique.popitem(last=False)
        for path in [path for path, value in _sources.items() if value == digest]:
            _sources.pop(path, None)
            _icons.pop(path, None)
        del _previews[digest]


def close():
    global _previews
    _queued.clear()
    _icons.clear()
    _sources.clear()
    _unique.clear()
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
