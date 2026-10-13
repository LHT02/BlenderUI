# SPDX-License-Identifier: GPL-2.0-or-later
"""Win10-only mouse bridge to a verified original Explorer notification Toolbar.

The toolbar itself translates mouse input using its true app callback/version.
No pointer-valued TB_HITTEST/TB_GETBUTTON messages, process-memory allocation,
mouse movement, foreign Shell_TrayWnd activation or Windows11 XAML message hacks.
"""
import ctypes as c
from ctypes import wintypes as w
from . import native_windows, notification_system

EVENTS = {'LEFT', 'RIGHT', 'DOUBLE', 'HOVER_ENTER', 'HOVER_LEAVE'}


def plan(event, x, y):
    if not isinstance(event, str) or event not in EVENTS or type(x) is not int or type(y) is not int or not 0 <= x <= 32767 or not 0 <= y <= 32767:
        raise ValueError('Invalid notification toolbar action')
    position = x | (y << 16)
    rows = {'LEFT': [(0x201, 1), (0x202, 0)], 'RIGHT': [(0x204, 2), (0x205, 0)],
            'DOUBLE': [(0x203, 1), (0x202, 0)], 'HOVER_ENTER': [(0x200, 0), (0x2a1, 0)],
            'HOVER_LEAVE': [(0x200, 0), (0x2a3, 0)]}[event]
    # Move the CONTROL's logical hot point outside its entire client before
    # WM_MOUSELEAVE. This is scalar input to the exact verified toolbar, not
    # physical SetCursorPos/SendInput or a click on a neighboring application's
    # icon. Win10 Explorer uses hot-item transitions for NIN_POPUPCLOSE.
    return [(message, flags, 0xffffffff if event == 'HOVER_LEAVE' and message == 0x200 else
             0 if message == 0x2a3 else position) for message, flags in rows]


def center(rect, client):
    if (not isinstance(rect, (tuple, list)) or not isinstance(client, (tuple, list)) or
            len(rect) != 4 or len(client) != 4 or any(type(value) is not int for value in (*rect, *client))):
        raise ValueError('Invalid notification toolbar button rectangle')
    left, top, right, bottom = rect
    if not (0 <= client[0] <= left < right <= client[2] <= 32767 and
            0 <= client[1] <= top < bottom <= client[3] <= 32767 and
            4 <= right - left <= 256 and 4 <= bottom - top <= 256):
        raise ValueError('Notification button is outside its original toolbar')
    return (left + right) // 2, (top + bottom) // 2


def action(source, provider, screen_rect, event, *, build=None, user=None, identity=None, container=None):
    build = notification_system.build_number() if build is None else build
    if type(build) is not int or not 10240 <= build < 22000:
        raise ValueError('Native toolbar proxy is only supported on Windows10')
    root, owner = source
    toolbar, expected = provider
    if not expected or owner[3] != 'Shell_TrayWnd' or expected[0] != owner[0] or expected[2] != owner[2] or expected[3] != 'ToolbarWindow32':
        raise ValueError('Unverified original notification toolbar')
    user = user or native_windows._api()
    identity = identity or (lambda handle: native_windows._identity(user, handle))
    parent, parent_identity = source
    if container:
        parent, parent_identity = container
        if (parent_identity[0] != owner[0] or parent_identity[2] != owner[2] or
                parent_identity[3] != 'NotifyIconOverflowWindow'):
            raise ValueError('Unverified original notification overflow window')
    for name, result, args in (
        ('IsChild', w.BOOL, [w.HWND, w.HWND]),
        ('GetClientRect', w.BOOL, [w.HWND, c.POINTER(w.RECT)]),
        ('ScreenToClient', w.BOOL, [w.HWND, c.POINTER(w.POINT)]),
        ('SendMessageTimeoutW', c.c_ssize_t, [w.HWND, w.UINT, w.WPARAM, w.LPARAM,
            w.UINT, w.UINT, c.POINTER(c.c_size_t)]),
    ):
        function = getattr(user, name)
        function.restype, function.argtypes = result, args
    if identity(root) != owner or identity(parent) != parent_identity or identity(toolbar) != expected or not user.IsChild(parent, toolbar):
        raise ValueError('Original notification toolbar changed')
    client, left, right = w.RECT(), w.POINT(*screen_rect[:2]), w.POINT(*screen_rect[2:])
    if not user.GetClientRect(toolbar, c.byref(client)) or not user.ScreenToClient(toolbar, c.byref(left)) or not user.ScreenToClient(toolbar, c.byref(right)):
        raise OSError('Cannot verify notification toolbar coordinates')
    x, y = center((left.x, left.y, right.x, right.y), (client.left, client.top, client.right, client.bottom))
    for message, flags, position in plan(event, x, y):
        if identity(root) != owner or identity(parent) != parent_identity or identity(toolbar) != expected or not user.IsChild(parent, toolbar):
            raise ValueError('Original notification toolbar changed during input')
        result = c.c_size_t()
        if not user.SendMessageTimeoutW(toolbar, message, flags, position, 0x3, 250, c.byref(result)):
            raise OSError('Original notification toolbar did not respond')
    return True
