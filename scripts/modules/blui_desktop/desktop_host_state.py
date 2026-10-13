# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded desktop-host transactions and durable rollback; no bpy or Win32 calls."""
from copy import deepcopy
import json
import os
import tempfile

MAX_BYTES = 131072
IDENTITY_FIELDS = ('handle', 'pid', 'thread_id', 'process_started', 'window_class')
SHELL_CLASSES = frozenset(('Progman', 'WorkerW', 'SHELLDLL_DefView', 'SysListView32'))
CANVAS_CLASSES = frozenset(('GHOST_WindowClass', 'BLUI_DesktopWindowClass'))


def identity(row, classes=None):
    if not isinstance(row, dict) or set(row) != set(IDENTITY_FIELDS):
        raise ValueError('Invalid desktop window identity')
    if (not isinstance(row['handle'], str) or not row['handle'].isdigit() or
            len(row['handle']) > 20 or not 0 < int(row['handle']) < 1 << 64 or
            any(type(row[key]) is not int or not 0 < row[key] <= 0xffffffff
                for key in ('pid', 'thread_id')) or
            not isinstance(row['process_started'], str) or
            not row['process_started'].isdigit() or len(row['process_started']) > 20 or
            not 0 < int(row['process_started']) < 1 << 64 or
            not isinstance(row['window_class'], str) or
            not 0 < len(row['window_class']) <= 255 or '\x00' in row['window_class'] or
            (classes is not None and row['window_class'] not in classes)):
        raise ValueError('Invalid desktop window identity')
    return dict(row)


def key(row):
    return tuple(row[field] for field in IDENTITY_FIELDS)


def rectangle(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4 or
            any(type(item) is not int or abs(item) > 1000000 for item in value) or
            value[0] >= value[2] or value[1] >= value[3]):
        raise ValueError('Invalid physical desktop rectangle')
    return list(value)


def surfaces(rows):
    if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= 32:
        raise ValueError('Supply one desktop canvas for each connected display')
    clean, devices, handles = [], set(), set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'handle', 'device', 'rect'}:
            raise ValueError('Invalid desktop canvas descriptor')
        handle, device = row['handle'], row['device']
        if (not isinstance(handle, str) or not handle.isdigit() or len(handle) > 20 or
                not 0 < int(handle) < 1 << 64 or handle in handles or
                not isinstance(device, str) or not 0 < len(device) <= 255 or
                '\x00' in device or device in devices):
            raise ValueError('Invalid or duplicate desktop canvas')
        handles.add(handle)
        devices.add(device)
        clean.append({'handle': handle, 'device': device, 'rect': rectangle(row['rect'])})
    return sorted(clean, key=lambda row: row['device'])


def shell_record(row):
    if not isinstance(row, dict) or set(row) != {'root', 'host', 'view', 'list', 'visible', 'raised'}:
        raise ValueError('Invalid original desktop record')
    result = {field: identity(row[field], SHELL_CLASSES) for field in ('root', 'host', 'view', 'list')}
    if (result['root']['window_class'] != 'Progman' or
            result['host']['window_class'] not in ('Progman', 'WorkerW') or
            result['view']['window_class'] != 'SHELLDLL_DefView' or
            result['list']['window_class'] != 'SysListView32' or
            (result['host']['window_class'] == 'Progman' and key(result['host']) != key(result['root'])) or
            any(type(row[field]) is not bool for field in ('visible', 'raised')) or
            len({(result[field]['pid'], result[field]['process_started']) for field in result}) != 1):
        raise ValueError('Invalid original desktop hierarchy')
    result.update(visible=row['visible'], raised=row['raised'])
    return result


def canvas_record(row):
    fields = {'window', 'instance', 'owner', 'host', 'style', 'extended_style', 'rect', 'visible', 'surface'}
    if not isinstance(row, dict) or set(row) != fields:
        raise ValueError('Invalid canvas rollback record')
    result = {'window': identity(row['window'], CANVAS_CLASSES),
              'owner': identity(row['owner']) if row['owner'] is not None else None,
              'host': identity(row['host'], ('Progman', 'WorkerW')),
              'rect': rectangle(row['rect']), 'surface': surfaces([row['surface']])[0]}
    if (not isinstance(row['instance'], str) or not row['instance'].isdigit() or
            len(row['instance']) > 20 or not 0 < int(row['instance']) < 1 << 64 or
            any(type(row[field]) is not int or not 0 <= row[field] <= 0xffffffff
            for field in ('style', 'extended_style')) or row['style'] & 0x40000000 or
            type(row['visible']) is not bool or
            result['window']['handle'] != result['surface']['handle'] or
            (result['owner'] is not None and result['owner']['pid'] != result['window']['pid'])):
        raise ValueError('Invalid original top-level canvas state')
    result.update(instance=row['instance'], style=row['style'],
                  extended_style=row['extended_style'], visible=row['visible'])
    return result


def payload(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'nonce', 'shell', 'canvases'} or
            type(value['version']) is not int or value['version'] != 1 or
            not isinstance(value['nonce'], str) or len(value['nonce']) != 32 or
            any(char not in '0123456789abcdef' for char in value['nonce']) or
            not isinstance(value['canvases'], list) or len(value['canvases']) > 32):
        raise ValueError('Invalid desktop recovery journal')
    shell = shell_record(value['shell']) if value['shell'] is not None else None
    rows = [canvas_record(row) for row in value['canvases']]
    if rows and shell is None or len({key(row['window']) for row in rows}) != len(rows):
        raise ValueError('Invalid desktop recovery transaction')
    return {'version': 1, 'nonce': value['nonce'], 'shell': shell, 'canvases': rows}


class Journal:
    def __init__(self, directory):
        if not isinstance(directory, str) or not os.path.isabs(directory) or '\x00' in directory:
            raise ValueError('Invalid desktop recovery directory')
        self.directory = directory
        self.path = os.path.join(directory, 'desktop-host-state.json')

    def read(self):
        try:
            with open(self.path, 'rb') as stream:
                data = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(data) > MAX_BYTES:
            raise ValueError('Desktop recovery file is too large')
        return payload(json.loads(data.decode('utf-8')))

    def write(self, value):
        data = json.dumps(payload(value), ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(data) > MAX_BYTES:
            raise ValueError('Desktop recovery transaction is too large')
        os.makedirs(self.directory, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='desktop-host-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


class Guard:
    """Journal-before-mutation, all-display-or-rollback, exact immutable HWND identities."""
    def __init__(self, backend, journal, nonce):
        self.backend, self.journal = backend, journal
        self.value = journal.read() or payload({'version': 1, 'nonce': nonce,
                                              'shell': None, 'canvases': []})
        self.nonce = nonce
        self.enabled = False
        self.need_rebind = False
        self.error = ''
        self.recovery_error = ''

    def restore(self):
        self.enabled = False
        shell = self.value['shell']
        # Make the original icons usable first, even if a canvas thread is hung.
        shell_done = shell is None or self.backend.restore_icons(shell)
        pending = []
        self.recovery_error = ''
        for row in self.value['canvases']:
            if not self.backend.restore_canvas(row):
                pending.append(row)
                self.recovery_error = getattr(self.backend, 'restore_error', '')[:2048]
        self.value = {'version': 1, 'nonce': self.value['nonce'],
                      'shell': shell if pending or not shell_done else None, 'canvases': pending}
        self.journal.write(self.value)
        return not pending and shell_done

    def reconcile(self, rows):
        rows = surfaces(rows)
        self.error, self.need_rebind = '', False
        if self.enabled and rows == [row['surface'] for row in self.value['canvases']]:
            return self.refresh()
        if not self.restore():
            raise RuntimeError('Desktop restoration is pending; cannot attach new canvases')
        try:
            shell = self.backend.discover()
            self.backend.validate_displays(rows)
            records = [self.backend.capture(row, shell) for row in rows]
            self.value = payload({'version': 1, 'nonce': self.nonce,
                                  'shell': shell, 'canvases': records})
            self.journal.write(self.value)  # Durable BEFORE parent/style/visibility mutations.
            for row in records:
                if not self.backend.attach(row, shell):
                    raise RuntimeError('Desktop canvas attachment failed')
            if not self.backend.hide_icons(shell):
                raise RuntimeError('Unable to hide the original desktop icons safely')
            self.enabled = True
            return True
        except (OSError, RuntimeError, ValueError) as exc:
            self.error = str(exc)[:2048]
            self.restore()
            return False

    def refresh(self):
        if not self.enabled:
            return self.restore() if self.value['shell'] or self.value['canvases'] else True
        try:
            shell = self.value['shell']
            if not self.backend.matches_shell(shell):
                raise RuntimeError('Windows desktop changed; reconnect the desktop canvases')
            self.backend.validate_displays([row['surface'] for row in self.value['canvases']])
            if not all(self.backend.attached(row, shell) for row in self.value['canvases']):
                raise RuntimeError('A desktop canvas was removed; reconnect the desktop canvases')
            if not self.backend.hide_icons(shell):
                raise RuntimeError('Windows desktop visibility changed')
            return True
        except (OSError, RuntimeError, ValueError) as exc:
            self.error, self.need_rebind = str(exc)[:2048], True
            self.restore()
            return False

    def status(self):
        return {'enabled': self.enabled, 'attached_count': len(self.value['canvases']) if self.enabled else 0,
                'pending_restore': bool(not self.enabled and (self.value['canvases'] or self.value['shell'])),
                'need_rebind': self.need_rebind,
                'handles': [row['window']['handle'] for row in self.value['canvases']] if self.enabled else [],
                'state': 'BLUI Desktop Connected' if self.enabled else 'Windows Desktop Restored',
                'error': self.error or self.recovery_error}


def recovery_snapshot(journal, nonce):
    """An older guardian must never restore a newer helper's transaction."""
    value = journal.read()
    return deepcopy(value) if value and value['nonce'] == nonce else None
