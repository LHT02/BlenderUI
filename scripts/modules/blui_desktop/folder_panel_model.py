# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure bounded synchronization plans for folder-backed native icon panels."""
import ntpath
from . import model


def directory(value):
    if (not isinstance(value, str) or not value or len(value) > 32768 or '\x00' in value or
            not ntpath.isabs(value)):
        raise ValueError('Choose an absolute folder path')
    return value


def changes(existing, rows, capacity, *, complete=True):
    """Remove only managed stale references, not manual cards or real filesystem entries."""
    if not isinstance(existing, list) or not isinstance(rows, list) or len(rows) > model.LIMIT:
        raise ValueError('Invalid folder panel snapshot')
    if type(capacity) is not int or not 0 <= capacity <= model.LIMIT:
        raise ValueError('Invalid folder panel capacity')
    if type(complete) is not bool:
        raise ValueError('Invalid folder panel snapshot completeness')
    target = {}
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('folder')) is not bool or
                not isinstance(row.get('name'), str) or len(row['name']) > 32768 or '\x00' in row['name']):
            raise ValueError('Invalid folder panel entry')
        path = directory(row.get('path'))
        target.setdefault(ntpath.normcase(ntpath.normpath(path)), row)
    present, removed, updated = set(), [], []
    for row in existing:
        path = ntpath.normcase(ntpath.normpath(row['path']))
        if row['managed'] and path not in target and complete:
            removed.append(row['id'])
        else:
            present.add(path)
            if row['managed'] and path in target:
                updated.append((row['id'], target[path]))
    available = capacity + len(removed)
    new = [row for path, row in target.items() if path not in present]
    return {'remove': removed, 'update': updated, 'add': new[:available],
            'truncated': len(new) > available}
