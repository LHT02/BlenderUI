# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded disposable native icon host; top-down RGBA, no bpy dependency."""
import base64
import os
import struct
import subprocess
import sys

BATCH = 4


def extract(paths):
    if not isinstance(paths, list) or not 0 < len(paths) <= BATCH:
        raise ValueError('Invalid desktop icon batch')
    executable = os.path.join(os.path.dirname(os.path.dirname(sys.prefix)), 'BLUI-fileicon.exe')
    rows = []
    for path in paths:
        if not isinstance(path, str) or not path or len(path) > 32768 or '\x00' in path:
            raise ValueError('Invalid icon path')
        try:
            if path.startswith('aumid:'):
                from . import package_icons, thumbnails
                asset = package_icons.resolve(path[6:])
                row = thumbnails.extract([asset])[0] if asset else thumbnails.empty(path)
                rows.append({**row, 'path': path})
                continue
            result = subprocess.run([executable, path], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            width, height = struct.unpack('<II', result.stdout[:8])
            pixels = result.stdout[8:]
            if result.returncode or not (0 < width <= 1024 and 0 < height <= 1024) or len(pixels) != width * height * 4:
                raise ValueError('Invalid native icon')
            rows.append({'path': path, 'width': width, 'height': height,
                         'rgba': base64.b64encode(pixels).decode('ascii')})
        except (OSError, ValueError, struct.error, subprocess.TimeoutExpired):
            rows.append({'path': path, 'width': 0, 'height': 0, 'rgba': ''})
    return rows
