# SPDX-License-Identifier: GPL-2.0-or-later
"""Helper-only, journalled Explorer reservation handoff; never writes SPI work areas.

ABM_SETSTATE temporarily enables only the system taskbar AUTOHIDE bit, as in
ManagedShell ExplorerHelper. Windows remains responsible for every other AppBar.
The original bit survives process/Explorer restarts; visibility has its own journal.
"""
import json
import os
import tempfile
import time
from .taskbar_native import identity_key, validate_record

AUTOHIDE = 1
MAX_BYTES = 8192


def _validate(entry):
    if entry is None:
        return None
    if (not isinstance(entry, dict) or set(entry) != {
            'primary', 'original_state', 'forced_state', 'changed'} or
            any(type(entry[key]) is not int or not 0 <= entry[key] <= 3
                for key in ('original_state', 'forced_state')) or
            type(entry['changed']) is not bool or
            entry['changed'] != (not bool(entry['original_state'] & AUTOHIDE)) or
            not entry['forced_state'] & AUTOHIDE):
        raise ValueError('Invalid Windows taskbar reservation recovery record')
    validate_record(entry['primary'])
    if entry['primary']['window_class'] != 'Shell_TrayWnd':
        raise ValueError('Only the verified primary Explorer bar controls reservation')
    return entry


class ReservationJournal:
    """Separate bounded journal retains compatibility with the visibility v1 file."""
    def __init__(self, directory):
        if not isinstance(directory, str) or not os.path.isabs(directory) or '\x00' in directory:
            raise ValueError('Invalid taskbar recovery directory')
        self.directory = directory
        self.path = os.path.join(directory, 'taskbar-reservation.json')

    def read(self):
        try:
            with open(self.path, 'rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(raw) > MAX_BYTES:
            raise ValueError('Windows taskbar reservation recovery file is too large')
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {'version', 'entry'} or
                type(value['version']) is not int or value['version'] != 1):
            raise ValueError('Invalid Windows taskbar reservation recovery file')
        return _validate(value['entry'])

    def write(self, entry):
        _validate(entry)
        data = json.dumps({'version': 1, 'entry': entry}, ensure_ascii=False).encode('utf-8')
        os.makedirs(self.directory, exist_ok=True)
        descriptor, path = tempfile.mkstemp(prefix='taskbar-reservation-', suffix='.tmp',
                                            dir=self.directory)
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


class ReservationController:
    """Every OS call is outside Blender; state writes are guarded by fresh identity.

    ensure returns True (reclaimed), None (Explorer/pending confirmation), or
    False (external choice/failure: stop hiding). restore keeps unresolved intent
    durable for the second guardian, including when no window was hidden yet.
    """
    def __init__(self, backend, journal, clock=time.monotonic):
        self.backend, self.journal, self.clock = backend, journal, clock
        self.entry = journal.read()
        self.reclaimed = False
        self.pending = self.entry is not None
        self.error = ''
        self._action = None
        self._deadline = 0.0

    def status(self):
        return {'reservation_reclaimed': self.reclaimed,
                'reservation_pending': self.pending, 'reservation_error': self.error}

    def _primary(self):
        row = self.backend.primary()
        if row is None:
            self.pending = True
            return None
        row = dict(row, visible=True)  # Recovery intent, not a visibility assertion.
        validate_record(row)
        if row['window_class'] != 'Shell_TrayWnd':
            raise ValueError('Unverified primary Windows taskbar')
        return row

    def _bind(self, row, state):
        original = state if self.entry is None else self.entry['original_state']
        entry = {'primary': row, 'original_state': original,
                 'forced_state': state | AUTOHIDE, 'changed': not bool(original & AUTOHIDE)}
        self.journal.write(entry)  # Durable BEFORE writes, also for a fresh Explorer epoch.
        self.entry = entry
        self._action = None
        self._deadline = 0.0

    def _write(self, row, state, action):
        if self._action != action:
            if not self.backend.set_reservation_state(row, state):
                self.error = 'Windows taskbar reservation update was not accepted'
                self.pending = True
                return None
            self._action, self._deadline = action, self.clock() + 2.0
        self.pending = True
        return None

    def ensure(self):
        self.error = ''
        row = self._primary()
        if row is None:
            self.reclaimed = False
            return None
        state = self.backend.reservation_state(row)
        if state is None:
            self.pending, self.reclaimed = True, False
            return None
        if self.entry is None or identity_key(row) != identity_key(self.entry['primary']):
            self._bind(row, state)
            if not state & AUTOHIDE:
                self._write(row, state | AUTOHIDE, 'hide')
                state = self.backend.reservation_state(row)
        if state is not None and state & AUTOHIDE:
            self.reclaimed, self.pending = True, False
            # Keep the hide action, so a later external toggle is not overwritten.
            return True
        self.reclaimed, self.pending = False, True
        if self._action == 'hide' and self.clock() < self._deadline:
            return None
        self.error = ('Windows taskbar auto-hide changed externally; Windows taskbar restored'
                      if self._action == 'hide' else
                      'Windows taskbar reservation could not be released')
        return False

    def restore(self):
        self.reclaimed = False
        if self.entry is None:
            self.pending = False
            return True
        if not self.entry['changed']:
            # The user already had auto-hide enabled: never turn it off.
            self.journal.write(None)
            self.entry, self.pending, self._action = None, False, None
            return True
        row = self._primary()
        if row is None:
            return False
        state = self.backend.reservation_state(row)
        if state is None:
            self.pending = True
            return False
        if identity_key(row) != identity_key(self.entry['primary']):
            # Current GetShellWindow Explorer owns this epoch. Never write a saved
            # HWND; persist the new exact identity before undoing our inherited bit.
            self._bind(row, state)
        if state & AUTOHIDE:
            self._write(row, state & ~AUTOHIDE, 'restore')  # Preserve current other bits.
            state = self.backend.reservation_state(row)
            if state is None or state & AUTOHIDE:
                if self._action == 'restore' and self.clock() >= self._deadline:
                    self._action = None  # Bounded retries; journal remains recoverable.
                self.pending = True
                return False
        self.journal.write(None)  # Clear only after confirmed restoration.
        self.entry, self.pending, self._action = None, False, None
        return True
