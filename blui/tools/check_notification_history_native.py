# SPDX-License-Identifier: GPL-2.0-or-later
"""ROOT-RUN ONLY: Win10 original Explorer bootstrap and OWN icon callbacks.

Temporarily adds ONE OWN-PID, uniquely named icon directly to the identity-verified
original Explorer receiver. It never broadcasts, hides/restacks Explorer, changes
auto-tray/preferences, invokes another app's icon or starts the BLUI relay host.
Finally deletes only the exact OWN icon. An inaccessible auto-hidden icon is a
reported unsupported provider, NOT a fabricated pass or a global settings change.
"""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import native_windows, notification_history, notification_host, notification_system

UID = 32742


class NotifyIconData(c.Structure):
    # Exact native SDK NOTIFYICONDATAW; Shell32 creates its own crossprocess wire.
    _fields_ = [('size', w.DWORD), ('handle', w.HWND), ('uid', w.UINT), ('flags', w.UINT),
                ('callback', w.UINT), ('icon', w.HICON), ('tip', w.WCHAR * 128),
                ('state', w.DWORD), ('state_mask', w.DWORD), ('info', w.WCHAR * 256),
                ('version', w.UINT), ('title', w.WCHAR * 64), ('info_flags', w.DWORD),
                ('guid', c.c_ubyte * 16), ('balloon', w.HICON)]


class NotifyIconIdentifier(c.Structure):
    _fields_ = [('size', w.DWORD), ('handle', w.HWND), ('uid', w.UINT), ('guid', c.c_ubyte * 16)]


def _main(own):
    if os.name != 'nt' or not 10240 <= notification_system.build_number() < 22000:
        raise SystemExit('Win10-only original toolbar QA')
    bridge, added = None, False
    callback = own.user.RegisterWindowMessageW('BLUI.QA.Historical.Notification.' + str(uuid.uuid4()))
    assert callback >= 0xc000
    original, callbacks = own._message, []
    def receive(handle, message, wparam, lparam):
        if message == callback:
            callbacks.append((int(wparam), int(lparam)))
            return 0
        return original(handle, message, wparam, lparam)
    own._wndproc = own._wndproc_type(receive)
    own.open()
    source = own._find_explorer()
    assert source, 'No identity-verified original Explorer notification provider'
    own_identity = native_windows._identity(own.user, own.tray)
    assert own_identity and own_identity[0] == os.getpid()
    own.user.LoadIconW.argtypes, own.user.LoadIconW.restype = [w.HINSTANCE, c.c_void_p], w.HICON
    icon = own.user.LoadIconW(None, c.c_void_p(32512))
    assert icon
    tip = 'BLUI OWN history QA ' + uuid.uuid4().hex[:12]
    shell = c.WinDLL('shell32', use_last_error=True, winmode=0x800)
    shell.Shell_NotifyIconW.argtypes, shell.Shell_NotifyIconW.restype = [w.DWORD, c.POINTER(NotifyIconData)], w.BOOL
    shell.Shell_NotifyIconGetRect.argtypes = [c.POINTER(NotifyIconIdentifier), c.POINTER(w.RECT)]
    shell.Shell_NotifyIconGetRect.restype = w.LONG
    assert c.sizeof(NotifyIconData) == (976 if c.sizeof(c.c_void_p) == 8 else 956)
    def send(message, version=0):
        assert native_windows._identity(own.user, own.tray) == own_identity
        assert own._explorer(source[0]) == source, 'Explorer identity changed; no stale foreign HWND messages'
        # Do not probe undocumented copydata variants. Shell32 is responsible
        # for signature, WOW64 wire size and OS-version-specific tray marshalling.
        assert own.user.FindWindowW('Shell_TrayWnd', None) == source[0], 'Another host owns first receiver; do not target it'
        value = NotifyIconData()
        value.size, value.handle, value.uid = c.sizeof(value), own.tray, UID
        value.flags, value.callback, value.icon, value.tip, value.version = 7, callback, icon, tip, version
        assert shell.Shell_NotifyIconW(message, c.byref(value)), 'Shell32 rejected OWN icon request'
    def pump(seconds=.2):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            own.pump(time.monotonic())
            time.sleep(.01)
    try:
        send(0)
        added = True
        send(4, version=4)
        pump()
        identifier = NotifyIconIdentifier()
        identifier.size, identifier.handle, identifier.uid = c.sizeof(identifier), own.tray, UID
        rect = w.RECT()
        status = shell.Shell_NotifyIconGetRect(c.byref(identifier), c.byref(rect))
        print(json.dumps({'own_registration': {'get_rect_hresult': hex(status & 0xffffffff),
            'rect': [rect.left, rect.top, rect.right, rect.bottom], 'identifier_size': c.sizeof(identifier),
            'own_hwnd': int(own.tray), 'own_uid': UID}}, ensure_ascii=False), flush=True)
        # Crucially: icon exists BEFORE bootstrap; no TaskbarCreated/re-register.
        bridge = notification_history.Bridge(own._find_explorer,
            lambda handle: native_windows._identity(own.user, handle))
        candidate, status = None, None
        for _attempt in range(6):
            rows, status = bridge.refresh()
            candidate = next((row for row in rows if row['tip'] == tip), None)
            if candidate and candidate['backend'] == 'TOOLBAR':
                break
            pump(.25)
        if not candidate or candidate['backend'] not in {'TOOLBAR', 'OVERFLOW'}:
            print(json.dumps({'result': 'UNSUPPORTED', 'bootstrap': status,
                'own_icon': {key: candidate[key] for key in ('key', 'tip', 'backend', 'actions')} if candidate else None,
                'own_metadata': bridge.metadata.observed.get((int(own.tray), UID)) if bridge.metadata else None,
                'metadata_diagnostics': bridge.metadata.diagnostics if bridge.metadata else {},
                'reason': 'OWN icon has no supported original provider; no auto-tray/preference changes'}, ensure_ascii=False), flush=True)
            return 2
        assert candidate['callback'] == 0 and candidate['version'] == 0, 'Do not invent app callback/version'
        evidence = {}
        expected = {'LEFT': {0x201, 0x202, 0x400}, 'RIGHT': {0x204, 0x205, 0x7b},
                    'DOUBLE': {0x203, 0x202}, 'HOVER_ENTER': {0x200, 0x2a1, 0x406}, 'HOVER_LEAVE': {0x2a3, 0x407}}
        events = ('LEFT', 'RIGHT', 'DOUBLE') if candidate['backend'] == 'OVERFLOW' else ('LEFT', 'RIGHT', 'DOUBLE', 'HOVER_ENTER', 'HOVER_LEAVE')
        for event in events:
            callbacks.clear()
            bridge.action(candidate['key'], event)
            pump(.5)
            messages = [value & 0xffff for _position, value in callbacks]
            print(json.dumps({'own_event': event, 'messages': messages}, ensure_ascii=False), flush=True)
            if event != 'HOVER_LEAVE':
                assert messages and any(message in expected[event] for message in messages), (event, callbacks)
            # Explorer does not promise forwarding WM_MOUSELEAVE/NIN_POPUPCLOSE
            # for every toolbar/version. action() has already verified actual
            # SendMessageTimeout delivery to the exact original toolbar. Empty
            # App callbacks are recorded as genuine behavior, never fabricated.
            assert all(value >> 16 == UID for _position, value in callbacks), ('Actual Explorer must preserve OWN v4 UID', callbacks)
            evidence[event] = messages
        if candidate['backend'] == 'OVERFLOW':
            # For hover evidence only, explicitly open this OWN icon's original
            # dropdown and locate the exact live toolbar item. No other app is
            # clicked and only this invocation's prior dropdown state is restored.
            from blui_desktop import notification_explorer_native as explorer
            state = explorer.open_overflow(source, bridge.session, bridge.identity)
            old_rows = bridge.rows
            try:
                fresh, _found = bridge._walk(source)
                items = [row for row in fresh if row['tip'] == tip and row['backend'] == 'TOOLBAR']
                assert len(items) == 1 and native_windows._identity(own.user, own.tray) == own_identity
                bridge.rows = fresh
                for event in ('HOVER_ENTER', 'HOVER_LEAVE'):
                    callbacks.clear()
                    bridge.action(items[0]['key'], event)
                    pump(.5)
                    messages = [value & 0xffff for _position, value in callbacks]
                    if event == 'HOVER_ENTER':
                        assert messages and any(message in expected[event] for message in messages), (event, callbacks)
                    assert all(value >> 16 == UID for _position, value in callbacks)
                    evidence[event] = messages
            finally:
                bridge.rows = old_rows
                explorer.close_overflow(source, bridge.session, bridge.identity, state)
        send(2)
        added = False
        pump()
        remaining, _state = bridge.refresh()
        assert not any(row['tip'] == tip for row in remaining), 'Deleted OWN icon must disappear'
        print(json.dumps({'result': 'PASS', 'platform': notification_system.build_number(),
            'bootstrap': status, 'own_backend': candidate['backend'], 'callbacks': evidence,
            'leave_behavior': 'Original toolbar hot-item cleanup delivered; App callback is not guaranteed by Explorer',
            'boundary': 'OWN-only Win10 Explorer original Toolbar, no broadcasts/remote memory/input movement/preferences'}, ensure_ascii=False, indent=2), flush=True)
        return 0
    finally:
        try:
            if added and own._explorer(source[0]) == source:
                send(2)
                pump()
        finally:
            if bridge:
                bridge.close()


def main():
    own = notification_host.Host(private=True)
    try:
        return _main(own)
    finally:
        own.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    raise SystemExit(main())
