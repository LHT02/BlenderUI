# SPDX-License-Identifier: GPL-2.0-or-later
"""Trusted Win32 HICON rasterization inside the disposable notification helper."""
import base64
import ctypes as c
from ctypes import wintypes as w

SIZE = 32


class _InfoHeader(c.Structure):
    _fields_ = [('size', w.DWORD), ('width', w.LONG), ('height', w.LONG),
                ('planes', w.WORD), ('bits', w.WORD), ('compression', w.DWORD),
                ('image_size', w.DWORD), ('xppm', w.LONG), ('yppm', w.LONG),
                ('used', w.DWORD), ('important', w.DWORD)]


class _Info(c.Structure):
    _fields_ = [('header', _InfoHeader), ('colors', w.DWORD * 3)]


def rgba_from_composites(black, white):
    """Recover straight-alpha top-down RGBA, including legacy monochrome masks."""
    if not isinstance(black, bytes) or not isinstance(white, bytes) or len(black) != len(white) or len(black) % 4:
        raise ValueError('Invalid notification icon pixels')
    rgba = bytearray(len(black))
    for index in range(0, len(black), 4):
        alpha = max(0, min(255, 255 - max(white[index + channel] - black[index + channel] for channel in range(3))))
        if alpha:
            for output, source in ((0, 2), (1, 1), (2, 0)):
                rgba[index + output] = min(255, round(black[index + source] * 255 / alpha))
        rgba[index + 3] = alpha
    return bytes(rgba)


def extract(icon):
    if type(icon) is not int or not 0 < icon <= 0xffffffff:
        return 0, 0, ''
    user, gdi = c.WinDLL('user32', use_last_error=True), c.WinDLL('gdi32', use_last_error=True)
    user.CopyIcon.argtypes, user.CopyIcon.restype = [w.HICON], w.HICON
    user.DestroyIcon.argtypes, user.DestroyIcon.restype = [w.HICON], w.BOOL
    user.GetDC.argtypes, user.GetDC.restype = [w.HWND], w.HDC
    user.ReleaseDC.argtypes, user.ReleaseDC.restype = [w.HWND, w.HDC], c.c_int
    user.DrawIconEx.argtypes = [w.HDC, c.c_int, c.c_int, w.HICON, c.c_int, c.c_int, w.UINT, w.HBRUSH, w.UINT]
    user.DrawIconEx.restype = w.BOOL
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [w.HDC], w.HDC
    gdi.CreateDIBSection.argtypes = [w.HDC, c.POINTER(_Info), w.UINT, c.POINTER(c.c_void_p), w.HANDLE, w.DWORD]
    gdi.CreateDIBSection.restype = w.HBITMAP
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [w.HDC, w.HANDLE], w.HANDLE
    gdi.DeleteObject.argtypes, gdi.DeleteObject.restype = [w.HANDLE], w.BOOL
    gdi.DeleteDC.argtypes, gdi.DeleteDC.restype = [w.HDC], w.BOOL
    copied = user.CopyIcon(icon)
    if not copied:
        return 0, 0, ''
    dc = bitmap = screen = old = None
    try:
        screen = user.GetDC(None)
        dc = gdi.CreateCompatibleDC(screen)
        header = _InfoHeader(c.sizeof(_InfoHeader), SIZE, -SIZE, 1, 32, 0, SIZE * SIZE * 4, 0, 0, 0, 0)
        info, bits = _Info(header), c.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, c.byref(info), 0, c.byref(bits), None, 0)
        if not dc or not bitmap or not bits.value:
            return 0, 0, ''
        old = gdi.SelectObject(dc, bitmap)
        composites = []
        for shade in (0, 255):
            c.memset(bits, shade, SIZE * SIZE * 4)
            if not user.DrawIconEx(dc, 0, 0, copied, SIZE, SIZE, 0, None, 3):
                return 0, 0, ''
            composites.append(c.string_at(bits, SIZE * SIZE * 4))
        rgba = rgba_from_composites(*composites)
        return SIZE, SIZE, base64.b64encode(rgba).decode('ascii')
    except (OSError, ValueError):
        return 0, 0, ''
    finally:
        if dc and old:
            gdi.SelectObject(dc, old)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if dc:
            gdi.DeleteDC(dc)
        if screen:
            user.ReleaseDC(None, screen)
        user.DestroyIcon(copied)
