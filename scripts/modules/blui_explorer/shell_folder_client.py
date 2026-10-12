# SPDX-License-Identifier: GPL-2.0-or-later
"""Merge folder associations from independent hosts; opaque IDs never cross hosts."""
import time
import uuid
import itertools
from .shell_client import Session

_command_ids = itertools.count(1)

class FolderSession:
    kind = 'folder'

    def __init__(self, paths, *, timeout=8.0, workers=None):
        self.paths = tuple(paths)
        self.timeout, self.workers = timeout, workers or {}
        self.helpers = {}
        try:
            for scope in ('folder', 'directory'):
                self.helpers[scope] = self._new_helper(scope)
        except Exception:
            self.close()
            raise
        self._clear()

    def _new_helper(self, scope):
        return Session(self.paths, scope=scope, timeout=self.timeout, worker=self.workers.get(scope))

    def _clear(self):
        self.token = uuid.uuid4().hex
        self.action = 'list'
        self.items, self.errors, self.updated_nodes = {}, {}, set()
        self.last_used, self.last_status = time.monotonic(), 0.0
        self._ids, self._commands = {}, {}
        self._changed = False
        self.error_shown = False

    @property
    def pending(self):
        return {(scope, serial): pending for scope, helper in self.helpers.items()
                for serial, pending in helper.pending.items()}

    @property
    def invoked(self):
        return any(helper.invoked for helper in self.helpers.values())

    def is_alive(self):
        return any(helper.is_alive() for helper in self.helpers.values())

    def _rows(self, scope, node):
        helper = self.helpers[scope]
        result = []
        for source in helper.items.get(node, []):
            row = dict(source)
            if row.get('submenu'):
                row['submenu'] = scope + ':' + row['submenu']
            elif not row['separator'] and row['enabled'] and 1 <= row['id'] <= 0x7fff:
                key = scope, row['id']
                if key not in self._ids:
                    opaque = next(_command_ids)
                    self._ids[key] = opaque
                    self._commands[opaque] = key
                row['id'] = self._ids[key]
            else:
                row['id'] = 0
            result.append(row)
        return result

    def _root(self):
        rows, labels = [], set()
        for scope, helper in self.helpers.items():
            if 'root' in helper.items:
                own_labels = set()
                for row in self._rows(scope, 'root'):
                    label = row['label'].casefold()
                    if not row['separator'] and label in labels:
                        continue  # Shared verbs/extensions are shown once.
                    if not row['separator']:
                        own_labels.add(label)
                    if row['separator'] and (not rows or rows[-1]['separator']):
                        continue
                    rows.append(row)
                labels.update(own_labels)
            elif 'root' in helper.errors:
                rows.append(dict(label='Some Windows extensions could not load; retry to load them',
                                 enabled=False, separator=False, id=0, localize=True))
            else:
                rows.append(dict(label='Loading folder-specific Windows extensions...', enabled=False,
                                 separator=False, id=0, localize=True, loading=True))
        while rows and rows[-1]['separator']:
            rows.pop()
        self.items['root'] = rows
        if all('root' in helper.errors for helper in self.helpers.values()):
            self.errors['root'] = next(iter(self.helpers.values())).errors['root']
        self.updated_nodes.add('root')

    def poll(self):
        self.updated_nodes.clear()
        changed = self._changed
        self._changed = False
        for scope, helper in self.helpers.items():
            if not helper.poll():
                continue
            changed = True
            for node in helper.updated_nodes:
                if node == 'root':
                    self._root()
                elif node == 'invoke':
                    if helper.items.pop('invoke', False):
                        self.items['invoke'] = True
                    if node in helper.errors:
                        self.errors['invoke'] = helper.errors[node]
                elif node != 'status':
                    key = scope + ':' + node
                    if node in helper.items:
                        self.items[key] = self._rows(scope, node)
                    if node in helper.errors:
                        self.errors[key] = helper.errors[node]
                    self.updated_nodes.add(key)
        return changed

    def request(self, op, **payload):
        if op == 'status':
            self.last_status = time.monotonic()
            for helper in self.helpers.values():
                if helper.invoked:
                    helper.request('status')
            return
        self.last_used = time.monotonic()
        if op == 'expand':
            scope, node = payload['node'].split(':', 1)
            self.helpers[scope].request('expand', node=node)
        elif op == 'invoke':
            target = self._commands.get(payload['command'])
            if not target:
                self.errors['invoke'] = 'Command does not belong to this menu session'
                self._changed = True
                return
            scope, command = target
            self.helpers[scope].request('invoke', command=command)
        else:
            raise ValueError('Unknown folder menu request')

    def reset(self, paths):
        if self.invoked or self.pending:
            raise RuntimeError('Only an idle Windows menu helper can be reused')
        self.paths = tuple(paths)
        for scope, helper in list(self.helpers.items()):
            if helper.errors or not helper.is_alive():
                helper.close()
                self.helpers[scope] = self._new_helper(scope)
            else:
                helper.reset(paths)
        self._clear()

    def close(self):
        for helper in self.helpers.values():
            helper.close()
