# SPDX-License-Identifier: GPL-2.0-or-later
"""Reserve native taskbar space via trusted Windows AppBar API, not SPI work-area writes.

Only the shell service timer calls reconcile; UI draws never call Win32.
Pass a device -> fresh live TASKBAR Window mapping. Every write revalidates exact
owned PID/thread/process-start/class, including ABM_REMOVE. No foreign window is
moved or resized. The root owner must close before native HWND destruction/load.
"""
import atexit
import ctypes as c
from ctypes import wintypes as w
import math
import os
from . import monitors, native_windows, window_placement

CALLBACK_MESSAGE = 0x82A7  # WM_APP + 0x2A7; native GHOST forwards position changes.
ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS = 0, 1, 2, 3
ABE_BOTTOM = 3
OWNER_PROPERTY = 'BLUI.AppBar.Registered'
TOKEN_PROPERTY = 'BLUI.AppBar.Token'
GENERATION_PROPERTY = 'BLUI.AppBar.Generation'
RESTART_PROPERTY = 'BLUI.AppBar.Restart'
FULLSCREEN_PROPERTY = 'BLUI.AppBar.Fullscreen'
_PROPERTIES = (OWNER_PROPERTY, TOKEN_PROPERTY, GENERATION_PROPERTY, RESTART_PROPERTY, FULLSCREEN_PROPERTY)


class _AppBarData(c.Structure):
    _fields_ = [('size', w.DWORD), ('window', w.HWND), ('callback', w.UINT),
                ('edge', w.UINT), ('rect', w.RECT), ('parameter', w.LPARAM)]


def _api():
    if os.name != 'nt':
        raise RuntimeError('Native AppBars require Windows')
    shell = c.WinDLL('shell32.dll', winmode=0x800, use_last_error=True)
    shell.SHAppBarMessage.argtypes = [w.DWORD, c.POINTER(_AppBarData)]
    shell.SHAppBarMessage.restype = c.c_size_t
    return shell


def _user_api():
    user = native_windows._api()
    for name, result, args in (
        ('GetPropW', w.HANDLE, [w.HWND, w.LPCWSTR]),
        ('SetPropW', w.BOOL, [w.HWND, w.LPCWSTR, w.HANDLE]),
        ('RemovePropW', w.HANDLE, [w.HWND, w.LPCWSTR]),
    ):
        function = getattr(user, name)
        function.restype, function.argtypes = result, args
    return user


def _property(user, handle, name):
    return int(user.GetPropW(handle, name) or 0)


def bottom_rect(display, height):
    if type(height) not in (int, float) or not math.isfinite(height) or not 16 <= height <= 1280:
        raise ValueError('Invalid logical AppBar height')
    rect = monitors._rect(display['rect'])
    pixels = max(1, min(rect[3] - rect[1] - 1, round(height * display['dpi'][1] / 96)))
    return [rect[0], rect[3] - pixels, rect[2], rect[3]]


def _contained(rect, display):
    rect = monitors._rect(rect)
    monitor = display['rect']
    if not (monitor[0] <= rect[0] < rect[2] <= monitor[2] and
            monitor[1] <= rect[1] < rect[3] <= monitor[3]):
        raise RuntimeError('Windows returned an off-monitor AppBar rectangle')
    return rect


_controllers = set()


class AppBarController:
    def __init__(self):
        self._entries = {}
        self._shell = None

    @staticmethod
    def _window(window, user):
        if window.blui_shell_role != 'TASKBAR':
            raise ValueError('Only a native BLUI taskbar can reserve an AppBar')
        handle = window_placement._handle(window.blui_native_handle)
        identity = window_placement._own(user, handle)
        style, extended = user.GetWindowLongPtrW(handle, -16), user.GetWindowLongPtrW(handle, -20)
        if style & 0x40000000 or not extended & 0x80 or not extended & 0x08000000:
            raise RuntimeError('The AppBar must be an owned no-activate top-level taskbar')
        return (window.as_pointer(), handle, identity)

    @staticmethod
    def _data(handle, rect=None):
        value = _AppBarData()
        value.size, value.window = c.sizeof(value), handle
        value.callback, value.edge = CALLBACK_MESSAGE, ABE_BOTTOM
        if rect is not None:
            value.rect = w.RECT(*rect)
        return value

    def _send(self, user, entry, message, data):
        if window_placement._own(user, entry['key'][1]) != entry['key'][2]:
            raise RuntimeError('The AppBar window identity changed before registration')
        return self._shell.SHAppBarMessage(message, c.byref(data))

    @staticmethod
    def _marked(user, entry):
        return (_property(user, entry['key'][1], OWNER_PROPERTY) == os.getpid() and
                _property(user, entry['key'][1], TOKEN_PROPERTY) == entry['token'])

    @staticmethod
    def _mark(user, entry):
        # The native callback compares Registered against its own process PID.
        # A registration token also protects same-process HWND/RNA reuse.
        handle = entry['key'][1]
        owner, token = _property(user, handle, OWNER_PROPERTY), _property(user, handle, TOKEN_PROPERTY)
        if (owner and owner != os.getpid()) or (token and token != entry['token']):
            raise RuntimeError('This taskbar is already managed by another AppBar registration')
        for name, value in ((TOKEN_PROPERTY, entry['token']), (GENERATION_PROPERTY, 1),
                            (RESTART_PROPERTY, 1), (FULLSCREEN_PROPERTY, 0), (OWNER_PROPERTY, os.getpid())):
            if window_placement._own(user, handle) != entry['key'][2]:
                raise RuntimeError('The AppBar changed before installing its callback marker')
            if value:
                if not user.SetPropW(handle, name, value):
                    raise OSError('Could not install the native AppBar callback marker')
            else:
                user.RemovePropW(handle, name)

    @staticmethod
    def _clear_marker(user, entry):
        if _property(user, entry['key'][1], TOKEN_PROPERTY) != entry['token']:
            return  # Also preserve other registrations on a failed marker install.
        for name in _PROPERTIES:
            if window_placement._own(user, entry['key'][1]) != entry['key'][2]:
                return
            user.RemovePropW(entry['key'][1], name)

    def _remove(self, device, user=None):
        entry = self._entries.pop(device, None)
        if entry is None or self._shell is None:
            return
        try:
            user = user or _user_api()
            # If a stored HWND has been reused, never unregister its new owner.
            if self._marked(user, entry):
                # Stop callback re-entry first, but keep exact identity checks.
                self._clear_marker(user, entry)
                self._send(user, entry, ABM_REMOVE, self._data(entry['key'][1]))
        except (OSError, RuntimeError, ValueError, AttributeError):
            pass  # Destroyed appbar HWNDs are removed by Windows itself.
        if not self._entries:
            _controllers.discard(self)

    def close_window(self, window):
        handle = window_placement._handle(window.blui_native_handle)
        for device, entry in tuple(self._entries.items()):
            if entry['key'][:2] == (window.as_pointer(), handle):
                self._remove(device)

    def close(self):
        for device in tuple(self._entries):
            self._remove(device)
        _controllers.discard(self)

    def snapshot(self):
        return {device: list(entry['rect']) for device, entry in self._entries.items()
                if entry['rect'] is not None}

    def invalidate(self):
        """RAM-only: request a fresh query after an isolated Explorer handoff."""
        for entry in self._entries.values():
            entry.pop('request', None)

    def position_changed(self, window):
        """Notify the shell after root moves a registered owned taskbar window."""
        user = _user_api()
        key = self._window(window, user)
        for entry in self._entries.values():
            if entry['key'] == key and self._marked(user, entry):
                self._send(user, entry, 9, self._data(key[1]))  # ABM_WINDOWPOSCHANGED
                return True
        return False

    def reconcile(self, windows, snapshot, desired_height_logical):
        """Return approved physical rects; root then places only those owned windows.

        Queries respect the original taskbar and all other AppBars. Keep the
        shell notifications callback forwarded, and call this on ABN_POSCHANGED,
        connected-display changes and user dimension changes. Query may also be
        polled at a bounded service cadence; unchanged rects send no SETPOS.
        """
        if (not isinstance(windows, dict) or len(windows) > monitors.MAX_MONITORS or
                any(not isinstance(device, str) or not 0 < len(device) <= 128 for device in windows)):
            raise ValueError('Invalid AppBar role window mapping')
        displays = {row['device']: row for row in monitors.validate(snapshot)['monitors']}
        # Validate height even if all monitors have just disconnected.
        if (type(desired_height_logical) not in (int, float) or
                not math.isfinite(desired_height_logical) or not 16 <= desired_height_logical <= 1280):
            raise ValueError('Invalid logical AppBar height')
        wanted = set(windows) & set(displays)
        if not wanted and not self._entries:
            return {}
        if self._shell is None:
            self._shell = _api()
        user = _user_api()
        for device in tuple(self._entries):
            if device not in wanted:
                self._remove(device, user)
        keys = {}
        for device in wanted:
            try:
                keys[device] = self._window(windows[device], user)
            except (OSError, RuntimeError, ValueError, AttributeError):
                self._remove(device, user)
                raise
        if len({key[1] for key in keys.values()}) != len(keys):
            raise ValueError('A taskbar HWND cannot reserve two displays')
        for device in sorted(wanted):
            key, display = keys[device], displays[device]
            entry = self._entries.get(device)
            if entry is not None and entry['key'] != key:
                self._remove(device, user)
                entry = None
            if entry is not None and not self._marked(user, entry):
                # Destroy/recreate can reuse both HWND and RNA in this process;
                # missing/different properties prove this is not our old registration.
                self._entries.pop(device, None)
                entry = None
            if entry is None:
                entry = {'key': key, 'rect': None}
                entry['token'] = id(entry)
                data = self._data(key[1])
                try:
                    self._mark(user, entry)
                    if not self._send(user, entry, ABM_NEW, data):
                        raise OSError('Windows could not register the BLUI taskbar')
                except (OSError, RuntimeError, ValueError, AttributeError):
                    self._clear_marker(user, entry)
                    raise
                entry['restart'] = _property(user, key[1], RESTART_PROPERTY)
                self._entries[device] = entry
                _controllers.add(self)
            try:
                restarted = _property(user, key[1], RESTART_PROPERTY)
                if restarted != entry['restart']:
                    # New Explorer has an empty AppBar registry. Do not REMOVE
                    # anything from it; re-register our still-live owned HWND.
                    if not self._send(user, entry, ABM_NEW, self._data(key[1])):
                        raise OSError('Windows could not restore the BLUI AppBar')
                    entry['restart'], entry['rect'] = restarted, None
                geometry = (tuple(display['rect']), tuple(display['work']), tuple(display['dpi']),
                            desired_height_logical, key)
                notification = (_property(user, key[1], GENERATION_PROPERTY), restarted,
                                _property(user, key[1], FULLSCREEN_PROPERTY))
                if entry['rect'] is not None and entry.get('request') == (geometry, notification):
                    continue  # No unchanged serial IPC to Explorer in the UI service.
                proposed = bottom_rect(display, desired_height_logical)
                pixels = proposed[3] - proposed[1]
                data = self._data(key[1], proposed)
                if not self._send(user, entry, ABM_QUERYPOS, data):
                    raise OSError('Windows could not query the AppBar position')
                # QUERYPOS subtracts occupied edges without preserving height.
                # Use full monitor coords (not the already-reserved work rect).
                data.rect.top = max(display['rect'][1], data.rect.bottom - pixels)
                queried = _contained([data.rect.left, data.rect.top,
                                      data.rect.right, data.rect.bottom], display)
                if queried != entry['rect']:
                    if not self._send(user, entry, ABM_SETPOS, data):
                        raise OSError('Windows could not reserve taskbar space')
                    approved = _contained([data.rect.left, data.rect.top,
                                           data.rect.right, data.rect.bottom], display)
                    if window_placement._own(user, key[1]) != key[2]:
                        raise RuntimeError('The AppBar window identity changed during positioning')
                    entry['rect'] = approved
                entry['generation'] = _property(user, key[1], GENERATION_PROPERTY)
                # SETPOS can synchronously notify this same bar. Remember the
                # final generation so our own notification doesn't create loops.
                entry['request'] = (geometry, (entry['generation'], entry['restart'],
                                               _property(user, key[1], FULLSCREEN_PROPERTY)))
            except (OSError, RuntimeError, ValueError, AttributeError):
                self._remove(device, user)
                raise
        return self.snapshot()


def close_all():
    for controller in tuple(_controllers):
        controller.close()


def notification_state(window):
    """Fresh validated native flags; suitable for timer placement decisions only."""
    if window.blui_shell_role != 'TASKBAR':
        return {'generation': 0, 'restart': 0, 'fullscreen': False}
    user = _user_api()
    key = AppBarController._window(window, user)
    if _property(user, key[1], OWNER_PROPERTY) != os.getpid():
        return {'generation': 0, 'restart': 0, 'fullscreen': False}
    state = {'generation': _property(user, key[1], GENERATION_PROPERTY),
             'restart': _property(user, key[1], RESTART_PROPERTY),
             'fullscreen': bool(_property(user, key[1], FULLSCREEN_PROPERTY))}
    if window_placement._own(user, key[1]) != key[2]:
        raise RuntimeError('The AppBar changed while reading its native notification')
    return state


def is_fullscreen(window):
    return notification_state(window)['fullscreen']


atexit.register(close_all)
