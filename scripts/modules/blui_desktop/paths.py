# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit Known Folder lookup; never guess Desktop when OneDrive redirects it."""
import ctypes
import os
import uuid


def desktop():
    if os.name == 'nt':
        value = ctypes.c_wchar_p()
        guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID('B4BFCC3A-DB2C-424C-B029-7FE99A87C641').bytes_le)
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        shell.SHGetKnownFolderPath.restype = ctypes.c_long
        ole = ctypes.WinDLL('ole32')
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        # DONT_VERIFY: reads the configured folder; does not touch slow/network desktop files.
        status = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0x4000, None, ctypes.byref(value))
        try:
            if status == 0 and value.value:
                return value.value
        finally:
            if value:
                ole.CoTaskMemFree(value)
    return os.path.join(os.path.expanduser('~'), 'Desktop')
