# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only, optional Explorer ITrayNotify metadata; no guessed click callbacks.

Undocumented COM interface observed in Apache-2.0 ManagedShell TrayNotify.cs.
Only RegisterCallback/UnregisterCallback are used, never SetPreference,
EnableAutoTray, DoAction, remote process memory or shell visibility changes.
"""
import ctypes as c
from ctypes import wintypes as w
import threading
import uuid
from .notification_uia_native import GUID, HRESULT, CALL, call, checked, release
from . import notification_pixels
from . import native_windows
from . import notification_path_native

CALLBACK_IID = 'd782ccba-afb0-43f1-94db-fda3779eaccb'
IUnknown = '00000000-0000-0000-c000-000000000046'


class NotifyItem(c.Structure):
    _fields_ = [('executable', c.c_void_p), ('tip', c.c_void_p), ('icon', w.HICON),
                ('handle', w.HWND), ('preference', w.DWORD), ('uid', w.UINT), ('guid', GUID)]


class _Interface(c.Structure):
    _fields_ = [('vtable', c.POINTER(c.c_void_p))]


def text(pointer, maximum):
    if not pointer:
        return ''
    result, value = [], c.cast(pointer, c.POINTER(w.WCHAR))
    for index in range(maximum):
        character = value[index]
        if character == '\0':
            return ''.join(result)
        result.append(character)
    return ''.join(result)


class Metadata:
    def __init__(self, session, identity):
        self.rows, self.lock, self.identity = {}, threading.Lock(), identity
        self.diagnostics = {'inactive': 0, 'stale_executable': 0, 'path_failure': 0, 'pixel_failure': 0, 'active': 0}
        self.path_forms = {}
        self.observed = {}  # Bounded helper-only diagnostics, never a wire/UI field.
        self.paths = notification_path_native.Resolver()
        self.client, self.cookie, self.registered = c.c_void_p(), c.c_ulonglong(), False
        self.functions = (
            CALL(HRESULT, c.c_void_p, c.POINTER(GUID), c.POINTER(c.c_void_p))(self._query),
            CALL(w.ULONG, c.c_void_p)(lambda _self: 2),
            CALL(w.ULONG, c.c_void_p)(lambda _self: 1),
            CALL(HRESULT, c.c_void_p, w.UINT, c.POINTER(NotifyItem))(self._notify),
        )
        self.table = (c.c_void_p * 4)(*(c.cast(fn, c.c_void_p).value for fn in self.functions))
        self.interface = _Interface(c.cast(self.table, c.POINTER(c.c_void_p)))
        try:
            self.client = session.create('25dead04-1eac-4911-9e3a-ad0a4ab560fd',
                                         'd133ce13-3537-48ba-93a7-afcd5d2053b4', context=4)
            checked(call(self.client, 3, HRESULT, [c.c_void_p, c.POINTER(c.c_ulonglong)],
                         c.byref(self.interface), c.byref(self.cookie)))
            self.registered = True
        except Exception:
            self.close()
            raise

    def _query(self, _self, iid, output):
        if not output:
            return -2147467261  # E_POINTER
        output[0] = None
        if bytes(iid.contents.data) in {uuid.UUID(CALLBACK_IID).bytes_le, uuid.UUID(IUnknown).bytes_le}:
            output[0] = c.addressof(self.interface)
            return 0
        return -2147467262  # E_NOINTERFACE

    def _notify(self, _self, event, pointer):
        try:
            if not pointer or event not in (0, 1, 2):
                return 0
            item = pointer.contents
            key = (int(item.handle or 0), item.uid)
            observation = {'event': int(event), 'icon_nonzero': bool(item.icon), 'stage': 'OWNER'}
            if len(self.observed) < 128 or key in self.observed:
                self.observed[key] = observation
            owner = self.identity(int(item.handle or 0))
            if not owner:
                return 0
            with self.lock:
                if event == 2:
                    self.rows.pop(key, None)
                elif len(self.rows) < 128 or key in self.rows:
                    # These are COM-marshalled LPWSTRs, not foreign process
                    # pointers. Keep only bounded text and copied pixel bytes.
                    tip, executable = text(item.tip, 127), text(item.executable, 32768)
                    actual = native_windows._metadata(owner[0]).get('executable', '')
                    kind = notification_path_native.form(executable)
                    self.path_forms[kind] = self.path_forms.get(kind, 0) + 1
                    observation.update(path_form=kind, tip=tip, stage='PIXELS')
                    if not item.icon:
                        observation['stage'] = 'INACTIVE'
                        self.diagnostics['inactive'] += 1
                        self.rows.pop(key, None)
                        return 0  # Persistent preference records are not live icons.
                    try:
                        matching = bool(executable and actual and self.paths.normalize(executable) == self.paths.normalize(actual))
                    except (OSError, ValueError):
                        observation['stage'] = 'PATH_FAILURE'
                        self.diagnostics['path_failure'] += 1
                        self.rows.pop(key, None)
                        return 0
                    if not matching:
                        observation['stage'] = 'PATH_MISMATCH'
                        self.diagnostics['stale_executable'] += 1
                        self.rows.pop(key, None)
                        return 0
                    pixels = notification_pixels.extract(int(item.icon))
                    if pixels[:2] != (32, 32):
                        observation['stage'] = 'PIXEL_FAILURE'
                        self.diagnostics['pixel_failure'] += 1
                        self.rows.pop(key, None)
                        return 0
                    self.diagnostics['active'] += 1
                    observation['stage'] = 'ACTIVE'
                    self.rows[key] = {'tip': tip, 'identity': owner,
                        'handle': key[0], 'uid': key[1], 'hidden': item.preference == 1,
                        'guid': str(uuid.UUID(bytes_le=bytes(item.guid.data))) if any(item.guid.data) else '',
                        'pixels': pixels}
        except Exception:
            pass  # Never unwind Python exceptions through an Explorer COM callback.
        return 0

    def snapshot(self):
        with self.lock:
            return [dict(row) for row in self.rows.values()
                    if self.identity(row['handle']) == row['identity']]

    def close(self):
        if self.registered:
            self.registered = False
            call(self.client, 4, HRESULT, [c.c_ulonglong], self.cookie.value)
        release(self.client)
