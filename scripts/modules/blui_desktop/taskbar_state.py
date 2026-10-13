# SPDX-License-Identifier: GPL-2.0-or-later
"""Crash-recoverable taskbar journal, independent of bpy and Win32 for testing."""
import json
import os
import tempfile
from .taskbar_native import identity_key, validate_record

MAX_BYTES = 65536


class Journal:
    def __init__(self, directory):
        if not isinstance(directory, str) or not os.path.isabs(directory) or '\x00' in directory:
            raise ValueError('Invalid taskbar recovery directory')
        self.directory = directory
        self.path = os.path.join(directory, 'taskbar-state.json')

    def read(self):
        try:
            with open(self.path, 'rb') as stream:
                data = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return []
        if len(data) > MAX_BYTES:
            raise ValueError('Windows taskbar recovery file is too large')
        payload = json.loads(data)
        if (not isinstance(payload, dict) or set(payload) != {'version', 'bars'} or
                type(payload['version']) is not int or payload['version'] != 1 or
                not isinstance(payload['bars'], list) or len(payload['bars']) > 32):
            raise ValueError('Invalid Windows taskbar recovery file')
        rows = [validate_record(row) for row in payload['bars']]
        if len({identity_key(row) for row in rows}) != len(rows):
            raise ValueError('Duplicate Windows taskbar recovery identity')
        return rows

    def write(self, rows):
        if len(rows) > 32:
            raise ValueError('Too many Windows taskbars')
        for row in rows:
            validate_record(row)
        data = json.dumps({'version': 1, 'bars': rows}, ensure_ascii=False).encode('utf-8')
        os.makedirs(self.directory, exist_ok=True)
        descriptor, path = tempfile.mkstemp(prefix='taskbar-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(path, self.path)
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


class Guard:
    def __init__(self, backend, journal):
        self.backend, self.journal = backend, journal
        self.rows = journal.read()
        self._durable_keys = {identity_key(row) for row in self.rows}
        self.enabled = False

    def restore(self):
        self.enabled = False
        pending = []
        for row in self.rows:
            if self.backend.matches(row):
                self.backend.set_visible(row, True)
                if not self.backend.visible(row):
                    pending.append(row)
        self.rows = pending
        self.journal.write(self.rows)
        self._durable_keys = {identity_key(row) for row in self.rows}
        return not pending

    def hide(self):
        self.enabled = True
        return self.refresh()

    def refresh(self):
        if not self.enabled:
            return self.restore() if self.rows else True
        # Drop vanished identities. Never apply a stale HWND to a replacement window.
        previous = [row for row in self.rows if self.backend.matches(row)]
        keys = {identity_key(row) for row in previous}
        for row in self.backend.enumerate():
            if row['visible'] and identity_key(row) not in keys:
                previous.append(validate_record(row))
                keys.add(identity_key(row))
        if len(previous) > 32:
            raise RuntimeError('Too many Windows taskbars')
        keys = {identity_key(row) for row in previous}
        changed = self._durable_keys != keys
        self.rows = previous
        # Durable intent must exist BEFORE the first hide, including Explorer restarts.
        if changed:
            self.journal.write(self.rows)
            self._durable_keys = keys
        for row in self.rows:
            self.backend.set_visible(row, False)
        return all(not self.backend.visible(row) for row in self.rows)

    def status(self):
        count = sum(self.backend.matches(row) and not self.backend.visible(row) for row in self.rows)
        return {'enabled': self.enabled, 'hidden_count': count,
                'state': 'Windows Taskbar Hidden' if self.enabled else 'Windows Taskbar Restored',
                'error': ''}
