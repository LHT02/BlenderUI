# SPDX-License-Identifier: GPL-2.0-or-later
"""Live DWM previews into a separate, verified BLUI-owned top-level popup.

Call update only from the shell service timer, with a fresh bpy Window; draw
reads snapshot only. DWM composites live windows without screenshots, Shell
extensions, disk caches or exported content. The owner must close this controller
before popup closure and on undo/load/unregister. The process also registers an
atexit cleanup; no foreign windows are moved, activated, restored or resized.

Microsoft API contract: DwmRegisterThumbnail requires a top-level destination
owned by this process; relationships are rendered only after properties update
and must be unregistered in this process. See blui/TASKBAR_PREVIEWS.md for links.
"""
import atexit
import ctypes as c
from ctypes import wintypes as w
import os
from . import native_windows, window_placement
from .taskbar_preview_layout import MAX_PREVIEWS, checked_rect, fit_rect


class _Properties(c.Structure):
    _fields_ = [('flags', w.DWORD), ('destination', w.RECT), ('source', w.RECT),
                ('opacity', c.c_ubyte), ('visible', w.BOOL), ('client_only', w.BOOL)]


def _dwm_api():
    if os.name != 'nt':
        raise RuntimeError('Live taskbar previews require Windows DWM')
    # Load only the trusted Windows system library, never an app-local DLL.
    dwm = c.WinDLL('dwmapi.dll', winmode=0x800, use_last_error=True)
    for name, args in (
        ('DwmRegisterThumbnail', [w.HWND, w.HWND, c.POINTER(w.HANDLE)]),
        ('DwmUnregisterThumbnail', [w.HANDLE]),
        ('DwmQueryThumbnailSourceSize', [w.HANDLE, c.POINTER(w.SIZE)]),
        ('DwmUpdateThumbnailProperties', [w.HANDLE, c.POINTER(_Properties)]),
        ('DwmGetWindowAttribute', [w.HWND, w.DWORD, c.c_void_p, w.DWORD]),
    ):
        function = getattr(dwm, name)
        function.argtypes, function.restype = args, w.LONG
    return dwm


def _user_api():
    user = native_windows._api()
    user.GetAncestor.argtypes, user.GetAncestor.restype = [w.HWND, w.UINT], w.HWND
    user.GetClientRect.argtypes, user.GetClientRect.restype = [w.HWND, c.POINTER(w.RECT)], w.BOOL
    user.GetWindowDisplayAffinity.argtypes = [w.HWND, c.POINTER(w.DWORD)]
    user.GetWindowDisplayAffinity.restype = w.BOOL
    return user


def _source(row):
    if not isinstance(row, dict):
        return None
    try:
        handle = window_placement._handle(row.get('handle'))
    except (ValueError, TypeError):
        return None
    pid, thread, started, name = (row.get(key) for key in
                                  ('pid', 'thread_id', 'process_started', 'window_class'))
    if (type(pid) is not int or not 0 < pid <= 0xffffffff or
            type(thread) is not int or not 0 < thread <= 0xffffffff or
            not isinstance(started, str) or not started.isdigit() or
            not 0 < len(started) <= 20 or int(started) <= 0 or
            not isinstance(name, str) or not 0 < len(name) <= 255 or '\x00' in name):
        return None
    return handle, (pid, thread, started, name)


# Retain active controllers until close, so a caller dropping its reference
# cannot orphan registrations before the process-wide cleanup runs.
_controllers = set()


class PreviewController:
    """At most four registrations; immutable identities, never retained bpy RNA."""
    def __init__(self):
        self._destination = None
        self._registrations = {}
        self._rows = ()
        self._dwm = None
        _controllers.add(self)

    def snapshot(self):
        return tuple({**row, 'rect': list(row['rect'])} for row in self._rows)

    def _remove(self, key):
        registration = self._registrations.pop(key, None)
        if registration and self._dwm is not None:
            try:
                self._dwm.DwmUnregisterThumbnail(registration['token'])
            except (OSError, ValueError):
                pass  # DWM may already have destroyed the source/destination.

    def close(self):
        for key in tuple(self._registrations):
            self._remove(key)
        self._destination, self._rows = None, ()
        _controllers.discard(self)

    @staticmethod
    def _destination_identity(window, user):
        if window.blui_shell_role not in ('TASK_CHOOSER', 'TASK_PREVIEW'):
            raise ValueError('A preview requires a separate BLUI shell popup')
        handle = window_placement._handle(window.blui_native_handle)
        identity = window_placement._own(user, handle)
        if user.GetAncestor(handle, 2) != handle:
            raise RuntimeError('A preview requires an owned top-level window')
        return (window.as_pointer(), handle, identity)

    @staticmethod
    def _source_status(user, dwm, handle, identity):
        if native_windows._identity(user, handle) != identity:
            return 'STALE'
        if user.GetAncestor(handle, 2) != handle or not user.IsWindowVisible(handle):
            return 'UNAVAILABLE'
        if user.IsIconic(handle):
            return 'MINIMIZED'
        affinity = w.DWORD()
        if user.GetWindowDisplayAffinity(handle, c.byref(affinity)) and affinity.value:
            return 'PROTECTED'
        cloaked = w.DWORD()
        if (dwm.DwmGetWindowAttribute(handle, 14, c.byref(cloaked), c.sizeof(cloaked)) == 0
                and cloaked.value):
            return 'UNAVAILABLE'
        return 'LIVE'

    def update(self, window, tasks, rects, *, excluded=()):
        """Update physical client slots and return RAM-only rows for labels/fallbacks.

        Only root-owned shell controller creates/positions/closes the native
        popup. Callers must supply all live shell HWNDs as excluded, and close
        here before the destination Window becomes invalid.
        """
        try:
            return self._update(window, tasks, rects, excluded=excluded)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
            self.close()
            raise

    def _update(self, window, tasks, rects, *, excluded):
        if (not isinstance(tasks, (tuple, list)) or len(tasks) > MAX_PREVIEWS or
                not isinstance(rects, (tuple, list)) or len(rects) != len(tasks)):
            raise ValueError('Invalid preview slots')
        slots = [checked_rect(rect) for rect in rects]
        user = _user_api()
        destination = self._destination_identity(window, user)
        if self._destination != destination:
            self.close()
            self._destination = destination
            _controllers.add(self)
        client = w.RECT()
        if (not user.GetClientRect(destination[1], c.byref(client)) or
                any(slot[2] > client.right or slot[3] > client.bottom for slot in slots)):
            raise ValueError('Preview slots must remain inside the popup client area')
        try:
            if self._dwm is None:
                self._dwm = _dwm_api()
        except (OSError, RuntimeError, AttributeError):
            self.close()
            self._rows = tuple({'handle': str(row.get('handle', '')) if isinstance(row, dict) else '',
                                'title': str(row.get('title', ''))[:512] if isinstance(row, dict) else '',
                                'status': 'UNAVAILABLE', 'rect': list(slot)}
                               for row, slot in zip(tasks, slots))
            return self.snapshot()
        excluded = {str(value) for value in excluded} | {str(destination[1])}
        keep, result = set(), []
        for row, slot in zip(tasks, slots):
            source = _source(row)
            state = {'handle': str(row.get('handle', '')) if isinstance(row, dict) else '',
                     'title': str(row.get('title', ''))[:512] if isinstance(row, dict) else '',
                     'status': 'STALE', 'rect': list(slot)}
            result.append(state)
            if source is None:
                continue
            handle, identity = source
            if str(handle) in excluded:
                state['status'] = 'EXCLUDED'
                continue
            state['status'] = self._source_status(user, self._dwm, handle, identity)
            if state['status'] != 'LIVE':
                continue
            key = (handle, identity)
            registration = self._registrations.get(key)
            if registration is None:
                # Revalidate both identities immediately before linking windows.
                if self._destination_identity(window, user) != destination:
                    raise RuntimeError('The preview destination changed')
                if native_windows._identity(user, handle) != identity:
                    state['status'] = 'STALE'
                    continue
                token = w.HANDLE()
                if self._dwm.DwmRegisterThumbnail(destination[1], handle, c.byref(token)) != 0 or not token.value:
                    state['status'] = 'UNAVAILABLE'
                    continue
                registration = {'token': token.value, 'rect': None}
                self._registrations[key] = registration
            size = w.SIZE()
            if (self._dwm.DwmQueryThumbnailSourceSize(registration['token'], c.byref(size)) != 0 or
                    not 0 < size.cx <= 32768 or not 0 < size.cy <= 32768):
                state['status'] = 'UNAVAILABLE'
                continue
            rect = fit_rect((size.cx, size.cy), slot)
            if self._destination_identity(window, user) != destination:
                raise RuntimeError('The preview destination changed during update')
            state['status'] = self._source_status(user, self._dwm, handle, identity)
            if state['status'] != 'LIVE':
                continue
            if rect != registration['rect']:
                if native_windows._identity(user, handle) != identity:
                    state['status'] = 'STALE'
                    continue
                if self._destination_identity(window, user) != destination:
                    raise RuntimeError('The preview destination changed before compositing')
                # Destination | opacity | visible | source-client-area flags.
                properties = _Properties(0x1 | 0x4 | 0x8 | 0x10, w.RECT(*rect), w.RECT(), 255, True, False)
                if self._dwm.DwmUpdateThumbnailProperties(registration['token'], c.byref(properties)) != 0:
                    state['status'] = 'UNAVAILABLE'
                    continue
                registration['rect'] = rect
            keep.add(key)
            state['rect'] = list(rect)
        for key in tuple(self._registrations):
            if key not in keep:
                self._remove(key)
        self._rows = tuple(result)
        return self.snapshot()


def close_all():
    for controller in tuple(_controllers):
        controller.close()


atexit.register(close_all)
