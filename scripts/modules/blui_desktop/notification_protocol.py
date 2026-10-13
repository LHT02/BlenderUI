# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure, bounded Shell notification protocol and versioned mouse callbacks.

Protocol reference: ManagedShell.Interop NativeMethods.Shell32 NOTIFYICONDATA
wire fields are 32-bit HWND/HICON on both sender architectures. This is a new
implementation of the Windows protocol, not copied ManagedShell source.
"""
import struct
import uuid

MAX_ICONS = 128
MAX_PACKET = 4096
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_STATE, NIF_GUID = 1, 2, 4, 8, 32


def _text(data):
    return data.decode('utf-16-le', errors='replace').split('\x00', 1)[0]


def parse(data):
    """Decode the cross-process 32-bit wire format, not native NOTIFYICONDATAW."""
    if not isinstance(data, bytes) or not 32 <= len(data) <= MAX_PACKET:
        raise ValueError('Invalid notification packet size')
    _magic, message, size, handle, uid, flags, callback, icon = struct.unpack_from('<8I', data)
    if message not in (0, 1, 2, 3, 4) or not 24 <= size <= 976 or not handle:
        raise ValueError('Invalid notification packet')
    tip_count = 64 if size <= 152 else 128
    tip_end = 32 + tip_count * 2
    if flags & NIF_TIP and len(data) < tip_end:
        raise ValueError('Truncated notification tooltip')
    if flags & NIF_STATE and len(data) < 296:
        raise ValueError('Truncated notification state')
    if message == 4 and len(data) < 812:
        raise ValueError('Truncated notification version')
    tip = _text(data[32:min(tip_end, len(data))])
    state, state_mask, version, guid = 0, 0, 0, ''
    # Modern wire has a 128-WCHAR tooltip; fields occur at fixed wire offsets.
    if len(data) >= 296:
        state, state_mask = struct.unpack_from('<II', data, 288)
    if len(data) >= 812:
        version = struct.unpack_from('<I', data, 808)[0]
    if flags & NIF_GUID:
        if len(data) < 960:
            raise ValueError('Truncated GUID notification packet')
        raw_guid = data[944:960]
        if any(raw_guid):
            guid = str(uuid.UUID(bytes_le=raw_guid))
    if flags & NIF_MESSAGE and not 0x400 <= callback <= 0xffff:
        raise ValueError('Invalid notification callback message')
    return {'message': message, 'handle': handle, 'uid': uid, 'flags': flags,
            'callback': callback, 'icon': icon, 'tip': tip, 'state': state,
            'state_mask': state_mask, 'version': version, 'guid': guid}


def key(record):
    return 'guid:' + record['guid'] if record['guid'] else 'hwnd:' + str(record['handle']) + ':' + str(record['uid'])


def callback_messages(record, event, x, y):
    if event not in ('LEFT', 'RIGHT', 'DOUBLE', 'HOVER_ENTER', 'HOVER_LEAVE'):
        raise ValueError('Invalid notification action')
    if any(type(value) is not int or not -32768 <= value <= 32767 for value in (x, y)):
        raise ValueError('Invalid notification anchor')
    version, uid = record['version'], record['uid']
    messages = {'LEFT': [0x201, 0x202], 'RIGHT': [0x204, 0x205],
                'DOUBLE': [0x203, 0x202], 'HOVER_ENTER': [0x200], 'HOVER_LEAVE': [0x2a3]}[event]
    if version >= 3 and event in ('LEFT', 'DOUBLE', 'RIGHT'):
        messages.append(0x7b if event == 'RIGHT' else 0x400)
    if version >= 4 and event in ('HOVER_ENTER', 'HOVER_LEAVE'):
        messages.append(0x406 if event == 'HOVER_ENTER' else 0x407)
    mouse = (x & 0xffff) | ((y & 0xffff) << 16)
    return [(mouse, message | ((uid & 0xffff) << 16)) if version >= 4 else (uid, message)
            for message in messages]


class Store:
    """Only the helper owns rows; main UI snapshots cannot manufacture callbacks."""
    def __init__(self, identity, pixels):
        self.identity, self.pixels = identity, pixels
        self.rows = {}
        self.revision = 0

    def _matches(self, row):
        return self.identity(row['handle']) == row['identity']

    def apply(self, packet):
        message, token = packet['message'], key(packet)
        old = self.rows.get(token)
        current = self.identity(packet['handle'])
        if current is None or not current[2]:
            return False
        if message == 2:
            if old and old['identity'] == current:
                self.rows.pop(token, None)
                self.revision += 1
            return True
        if message == 3:
            return True
        if message == 4:
            if old is None or old['identity'] != current or packet['version'] > 4:
                return False
            old['version'] = packet['version']
            self.revision += 1
            return True
        if old is None or message == 0:
            if not packet['flags'] & NIF_MESSAGE:
                return False
            if len(self.rows) >= MAX_ICONS and token not in self.rows:
                return False
            row = {'key': token, 'handle': packet['handle'], 'uid': packet['uid'],
                   'guid': packet['guid'], 'identity': current, 'callback': 0, 'version': 0,
                   'tip': '', 'hidden': False, 'width': 0, 'height': 0, 'rgba': ''}
        else:
            if old['identity'] != current:
                return False
            row = dict(old)
        flags = packet['flags']
        if flags & NIF_MESSAGE:
            row['callback'] = packet['callback']
        if flags & NIF_TIP:
            row['tip'] = packet['tip'][:127]
        if flags & NIF_STATE and packet['state_mask'] & 1:
            row['hidden'] = bool(packet['state'] & 1)
        if flags & NIF_ICON:
            row['width'], row['height'], row['rgba'] = self.pixels(packet['icon'])
        if self.identity(packet['handle']) != current:
            return False
        self.rows[token] = row
        self.revision += 1
        return True

    def prune(self):
        for token, row in list(self.rows.items()):
            if not self._matches(row):
                self.rows.pop(token, None)
                self.revision += 1

    def snapshot(self):
        result = []
        for row in self.rows.values():
            pid, thread, started, name = row['identity']
            result.append({name: value for name, value in row.items() if name != 'identity'} |
                          {'handle': str(row['handle']), 'pid': pid, 'thread_id': thread,
                           'process_started': started, 'window_class': name})
        return result

    def action(self, token, event, x, y, post, allow_foreground):
        row = self.rows.get(token)
        if row is None or not row['callback'] or not self._matches(row):
            raise ValueError('This notification icon changed or exited')
        callbacks = callback_messages(row, event, x, y)
        if event in ('LEFT', 'RIGHT', 'DOUBLE'):
            allow_foreground(row['identity'][0])
        for wparam, lparam in callbacks:
            if not self._matches(row):
                raise ValueError('This notification icon changed or exited')
            if not post(row['handle'], row['callback'], wparam, lparam):
                raise OSError('Windows refused the notification callback')
        return True
