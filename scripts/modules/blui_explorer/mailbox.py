# SPDX-License-Identifier: GPL-2.0-or-later
"""Atomic local messages. No Python threads or blocking pipe I/O in Blender."""
import json
import os
from pathlib import Path


def publish(directory, name, payload):
    target = Path(directory) / name
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=True, default=os.fspath), encoding='utf-8')
    os.replace(temporary, target)


def take(directory, name):
    target = Path(directory) / name
    try:
        value = json.loads(target.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    target.unlink()
    return value
