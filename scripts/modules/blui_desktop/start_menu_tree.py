# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure, bounded presentation of Programs folders and the classic Start home list.

The folder tree is derived from the checked relative path, never a launch target.
Open-Shell's Windows 7 layout is a design reference, not copied implementation.
"""
import hashlib
from . import start_menu_model as schema


def folder_key(parts):
    return hashlib.sha256('\0'.join(schema.folded(part) for part in parts).encode('utf-8')).hexdigest()


def app_item(row, depth=0):
    return {'kind': 'APP', 'name': row['name'], 'app_id': row['id'],
            'path': row['path'], 'folder_id': '', 'depth': depth, 'expanded': False}


def header(name):
    return {'kind': 'HEADER', 'name': name, 'app_id': '', 'path': '',
            'folder_id': '', 'depth': 0, 'expanded': False}


def programs(rows, expanded=()):
    """Merge common/user folder names, preserve app identities, and flatten open branches."""
    if len(rows) > schema.MAX_APPS:
        raise ValueError('Invalid Start menu tree size')
    opened = {schema.key(identity) for identity in expanded}
    if len(opened) > schema.MAX_APPS * 8:
        raise ValueError('Invalid Start menu expanded folder count')
    root = {'folders': {}, 'apps': []}
    for row in rows:
        parts = schema.relative_path(row['relative']).split('\\')[:-1]
        if len(parts) > 8:
            raise ValueError('Invalid Start menu folder depth')
        node = root
        for depth, part in enumerate(parts):
            folded = schema.folded(part)
            node = node['folders'].setdefault(folded, {
                'name': part, 'key': folder_key(parts[:depth + 1]), 'folders': {}, 'apps': []})
        node['apps'].append(row)
    result = []

    def emit(node, depth):
        for folded in sorted(node['folders']):
            child = node['folders'][folded]
            is_open = child['key'] in opened
            result.append({'kind': 'FOLDER', 'name': child['name'], 'app_id': '', 'path': '',
                           'folder_id': child['key'], 'depth': depth, 'expanded': is_open})
            if is_open:
                emit(child, depth + 1)
        result.extend(app_item(row, depth) for row in sorted(node['apps'],
                      key=lambda item: (schema.folded(item['name']), item['source'] != 'user', item['id'])))

    emit(root, 0)
    return result


def home(rows, pins, recent):
    """Pinned programs first, then recent programs, without duplicate launch buttons."""
    result, used = [], set()
    pinned = schema.selected(rows, pins)
    if pinned:
        result.append(header('Pinned Apps'))
        result.extend(app_item(row) for row in pinned)
        used.update(row['id'] for row in pinned)
    latest = [row for row in schema.selected(rows, recent) if row['id'] not in used]
    if latest:
        result.append(header('Recently Opened Apps'))
        result.extend(app_item(row) for row in latest)
    if not pinned and not latest and rows:
        # A fresh profile should be useful before the first successful launch.
        result.append(header('Programs'))
        result.extend(app_item(row) for row in rows[:12])
    return result


def contents(value, section='HOME', query='', expanded=()):
    if query.strip():
        return [app_item(row) for row in schema.search(value['rows'], query)]
    if section == 'ALL':
        return programs(value['rows'], expanded)
    if section in {'PINNED', 'RECENT'}:
        keys = value['pins' if section == 'PINNED' else 'recent']
        return [app_item(row) for row in schema.selected(value['rows'], keys)]
    return home(value['rows'], value['pins'], value['recent'])
