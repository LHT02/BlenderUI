# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded isolated File Browser previews. No bpy dependency or main-thread disk access."""
import base64
import ntpath
import os
import re
import struct
import subprocess
import sys
import tempfile

BATCH = 2
MAX_DIMENSION = 256
MAX_PIXELS = MAX_DIMENSION * MAX_DIMENSION
MAX_REPLY = 12 + MAX_PIXELS * 4
TIMEOUT = 3.5

# This is only an immediate no-I/O queue filter. The native helper uses the authoritative
# ED_path_extension_type + ImBuf feature set, including .ogg's video/audio distinction.
_SUFFIXES = frozenset({
    '.png', '.tga', '.bmp', '.jpg', '.jpeg', '.sgi', '.rgb', '.rgba', '.tif', '.tiff', '.tx',
    '.jp2', '.j2c', '.hdr', '.dds', '.dpx', '.cin', '.exr', '.psd', '.pdd', '.psb', '.webp',
    '.avi', '.flc', '.mov', '.movie', '.mp4', '.m4v', '.m2v', '.m2t', '.m2ts', '.mts', '.ts',
    '.mv', '.avs', '.wmv', '.ogv', '.ogg', '.r3d', '.dv', '.mpeg', '.mpg', '.mpg2', '.vob',
    '.mkv', '.flv', '.divx', '.xvid', '.mxf', '.webm', '.blend', '.ble', '.ttf', '.ttc',
    '.pfb', '.otf', '.otc', '.woff', '.woff2',
})


def valid_path(path):
    return (isinstance(path, str) and bool(path) and len(path) <= 32768 and
            '\x00' not in path and ntpath.isabs(path))


def candidate(path, folder=False):
    if folder or not valid_path(path):
        return False
    normalized = path.replace('\\', '/').lower()
    return (ntpath.splitext(normalized)[1] in _SUFFIXES or normalized.endswith('.blend.gz') or
            re.search(r'\.blend\d+$', normalized) is not None or
            re.search(r'\.(?:blend|ble)/[^/]+/[^/]+$', normalized) is not None)


def executable():
    return os.path.join(os.path.dirname(os.path.dirname(sys.prefix)), 'BLUI.exe')


def empty(path):
    return {'path': path, 'width': 0, 'height': 0, 'rgba': ''}


def decode_reply(data):
    if not isinstance(data, bytes) or not 12 <= len(data) <= MAX_REPLY:
        raise ValueError('Invalid native preview size')
    magic, width, height = struct.unpack('<4sII', data[:12])
    if magic != b'BTP1' or not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION):
        raise ValueError('Invalid native preview header')
    rgba = data[12:]
    if len(rgba) != width * height * 4:
        raise ValueError('Invalid native preview pixels')
    return width, height, rgba


def validate_pixels(rows):
    if not isinstance(rows, list) or len(rows) > BATCH:
        raise ValueError('Invalid desktop preview result')
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'path', 'width', 'height', 'rgba'} or
                not valid_path(row.get('path')) or
                any(type(row.get(key)) is not int or not 0 <= row[key] <= MAX_DIMENSION
                    for key in ('width', 'height')) or
                (row['width'] == 0) != (row['height'] == 0) or
                not isinstance(row.get('rgba'), str) or len(row['rgba']) > 349528):
            raise ValueError('Invalid desktop preview pixels')
        try:
            rgba = base64.b64decode(row['rgba'], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid desktop preview encoding') from exc
        if len(rgba) != row['width'] * row['height'] * 4:
            raise ValueError('Invalid desktop preview pixels')


def extract(paths):
    if (not isinstance(paths, (list, tuple)) or not 0 < len(paths) <= BATCH or
            any(not valid_path(path) for path in paths)):
        raise ValueError('Invalid desktop preview paths')
    rows = []
    # Called only inside the desktop worker. Each native decoder owns its own deadline;
    # a cancelled parent cannot leave a permanent decoder or UI window behind.
    with tempfile.TemporaryDirectory(prefix='blui_filepreview_') as directory:
        for index, path in enumerate(paths):
            row = empty(path)
            if candidate(path):
                result_path = os.path.join(directory, str(index) + '.rgba')
                try:
                    result = subprocess.run([executable(), '--blui-file-preview', path, result_path],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=TIMEOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    if result.returncode == 0:
                        with open(result_path, 'rb') as stream:
                            width, height, rgba = decode_reply(stream.read(MAX_REPLY + 1))
                        row = {'path': path, 'width': width, 'height': height,
                               'rgba': base64.b64encode(rgba).decode('ascii')}
                except (OSError, ValueError, struct.error, subprocess.TimeoutExpired):
                    pass
            rows.append(row)
    return rows
