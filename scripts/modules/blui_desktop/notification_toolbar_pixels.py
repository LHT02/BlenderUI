# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only original Toolbar glyph fallback when COM tooltip mapping is absent.

PrintWindow targets only the exact notification Toolbar, never a desktop or app.
Only its freshly verified UIA button rectangle is retained; no other button pixels
leave the helper. Real HICON pixels remain preferred and retain their full alpha.
"""
import base64
import ctypes as c
from ctypes import wintypes as w
from collections import Counter
from . import native_windows, notification_pixels, notification_toolbar_native


def crop_glyph(raw, width, height, rect):
    """Crop first, remove only a uniform verified border, then scale to 32 RGBA."""
    if not isinstance(raw, bytes) or len(raw) != width * height * 4:
        raise ValueError('Invalid original toolbar pixels')
    left, top, right, bottom = rect
    if not 0 <= left < right <= width or not 0 <= top < bottom <= height:
        raise ValueError('Invalid original toolbar crop')
    cropped = [raw[(y * width + x) * 4:(y * width + x + 1) * 4]
               for y in range(top, bottom) for x in range(left, right)]
    size_x, size_y = right - left, bottom - top
    border = [cropped[y * size_x + x][:3] for y in range(size_y) for x in range(size_x)
              if x in (0, size_x - 1) or y in (0, size_y - 1)]
    background, frequency = Counter(border).most_common(1)[0]
    # A mixed/animated/hover border cannot safely be made transparent. Treat it
    # as unavailable, not a screenshot with another control's theme baked in.
    if frequency < len(border) * .9:
        raise ValueError('Original toolbar glyph has no unambiguous background')
    pixels = bytearray(size_x * size_y * 4)
    occupied = []
    for index, value in enumerate(cropped):
        if max(abs(value[channel] - background[channel]) for channel in range(3)) > 4:
            pixels[index * 4:index * 4 + 4] = bytes((value[2], value[1], value[0], 255))
            occupied.append((index % size_x, index // size_x))
    if len(occupied) < 4:
        raise ValueError('Original toolbar provider did not render a glyph')
    bounds = (min(x for x, _y in occupied), min(y for _x, y in occupied),
              max(x for x, _y in occupied) + 1, max(y for _x, y in occupied) + 1)
    # Keep the original aspect, center on a transparent 32-square. This is an
    # actual 16/24px native glyph fallback, not a claim of recovering 32px HICON.
    glyph_w, glyph_h = bounds[2] - bounds[0], bounds[3] - bounds[1]
    scale = min(28 / glyph_w, 28 / glyph_h)
    output_w, output_h = max(1, round(glyph_w * scale)), max(1, round(glyph_h * scale))
    output, offset_x, offset_y = bytearray(32 * 32 * 4), (32 - output_w) // 2, (32 - output_h) // 2
    for y in range(output_h):
        for x in range(output_w):
            source_x = bounds[0] + min(glyph_w - 1, x * glyph_w // output_w)
            source_y = bounds[1] + min(glyph_h - 1, y * glyph_h // output_h)
            source, target = (source_y * size_x + source_x) * 4, ((y + offset_y) * 32 + x + offset_x) * 4
            output[target:target + 4] = pixels[source:source + 4]
    return 32, 32, base64.b64encode(output).decode('ascii')


def capture(source, provider, screen_rect, identity, *, container=None):
    """No visibility/foreground changes, movement, input or remote memory access."""
    user, gdi = native_windows._api(), c.WinDLL('gdi32', use_last_error=True, winmode=0x800)
    root, owner = source
    toolbar, expected = provider
    parent, parent_owner = container or source
    if (owner[3] != 'Shell_TrayWnd' or expected[0] != owner[0] or expected[2] != owner[2] or
            expected[3] != 'ToolbarWindow32' or parent_owner[0] != owner[0] or parent_owner[2] != owner[2] or
            parent_owner[3] not in {'Shell_TrayWnd', 'NotifyIconOverflowWindow'}):
        return 0, 0, ''
    for name, result, args in (
        ('IsChild', w.BOOL, [w.HWND, w.HWND]), ('GetClientRect', w.BOOL, [w.HWND, c.POINTER(w.RECT)]),
        ('GetWindowRect', w.BOOL, [w.HWND, c.POINTER(w.RECT)]),
        ('ScreenToClient', w.BOOL, [w.HWND, c.POINTER(w.POINT)]),
        ('PrintWindow', w.BOOL, [w.HWND, w.HDC, w.UINT]),
    ):
        fn = getattr(user, name)
        fn.restype, fn.argtypes = result, args
    for name, result, args in (
        ('CreateCompatibleDC', w.HDC, [w.HDC]),
        ('CreateDIBSection', w.HBITMAP, [w.HDC, c.POINTER(notification_pixels._Info), w.UINT, c.POINTER(c.c_void_p), w.HANDLE, w.DWORD]),
        ('SelectObject', w.HANDLE, [w.HDC, w.HANDLE]), ('DeleteObject', w.BOOL, [w.HANDLE]), ('DeleteDC', w.BOOL, [w.HDC]),
    ):
        fn = getattr(gdi, name)
        fn.restype, fn.argtypes = result, args
    foreground = user.GetForegroundWindow()
    foreground_owner = identity(foreground) if foreground else None
    if foreground and foreground_owner is None:
        return 0, 0, ''
    def fresh():
        return bool(identity(root) == owner and identity(toolbar) == expected and identity(parent) == parent_owner and
                    user.IsChild(parent, toolbar) and user.GetForegroundWindow() == foreground and
                    (not foreground or identity(foreground) == foreground_owner))
    if not fresh():
        return 0, 0, ''
    client, window_rect = w.RECT(), w.RECT()
    left, right = w.POINT(*screen_rect[:2]), w.POINT(*screen_rect[2:])
    if (not user.GetClientRect(toolbar, c.byref(client)) or not user.GetWindowRect(toolbar, c.byref(window_rect)) or
            not user.ScreenToClient(toolbar, c.byref(left)) or not user.ScreenToClient(toolbar, c.byref(right))):
        return 0, 0, ''
    rect = (left.x, left.y, right.x, right.y)
    dc = bitmap = old = None
    try:
        notification_toolbar_native.center(rect, (client.left, client.top, client.right, client.bottom))
        width, height = client.right, client.bottom
        if not 1 <= width <= 8192 or not 1 <= height <= 512 or width * height * 4 > 4 * 1024 * 1024:
            return 0, 0, ''
        dc, bits = gdi.CreateCompatibleDC(None), c.c_void_p()
        info = notification_pixels._Info(notification_pixels._InfoHeader(
            c.sizeof(notification_pixels._InfoHeader), width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0))
        bitmap = gdi.CreateDIBSection(dc, c.byref(info), 0, c.byref(bits), None, 0)
        if not dc or not bitmap or not bits.value:
            return 0, 0, ''
        old = gdi.SelectObject(dc, bitmap)
        c.memset(bits, 0, width * height * 4)
        if not fresh() or not user.PrintWindow(toolbar, dc, 1):
            return 0, 0, ''
        current = w.RECT()
        if (not fresh() or not user.GetWindowRect(toolbar, c.byref(current)) or
                (current.left, current.top, current.right, current.bottom) !=
                (window_rect.left, window_rect.top, window_rect.right, window_rect.bottom)):
            return 0, 0, ''
        return crop_glyph(c.string_at(bits, width * height * 4), width, height, rect)
    except (ValueError, OSError):
        return 0, 0, ''
    finally:
        if dc and old:
            gdi.SelectObject(dc, old)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if dc:
            gdi.DeleteDC(dc)
