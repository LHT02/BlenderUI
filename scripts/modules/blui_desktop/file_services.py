# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit FIFO filesystem actions, never run from native UI draw or timers."""
import ctypes
from ctypes import wintypes as w
import os
import time


def isolated_recycle(paths):
    from .client import Job
    job = Job('recycle', paths, timeout=60)
    try:
        while not job.done():
            time.sleep(.02)
        job.result()
    finally:
        job.close()


def rename(source, target):
    from blui_explorer.file_tasks import canonical
    if source == target:
        return
    if os.path.lexists(target) and canonical(source) != canonical(target):
        raise FileExistsError('An item with that name already exists')
    os.rename(source, target)


def recycle(paths):
    if (os.name != 'nt' or not isinstance(paths, list) or not 0 < len(paths) <= 1000 or
            any(not isinstance(path, str) or not path or '\x00' in path or len(path) > 32768 for path in paths)):
        raise ValueError('Invalid recycle request')
    class FileOperation(ctypes.Structure):
        _fields_ = [('hwnd', w.HWND), ('function', w.UINT), ('source', w.LPCWSTR),
                    ('target', w.LPCWSTR), ('flags', w.WORD), ('aborted', w.BOOL),
                    ('mapping', ctypes.c_void_p), ('progress_title', w.LPCWSTR)]
    sources = '\0'.join(os.path.abspath(path) for path in paths) + '\0\0'
    request = FileOperation(None, 3, sources, None, 0x40 | 0x10 | 0x400, False, None, None)
    api = ctypes.WinDLL('shell32', use_last_error=True)
    api.SHFileOperationW.argtypes = [ctypes.POINTER(FileOperation)]
    api.SHFileOperationW.restype = ctypes.c_int
    status = api.SHFileOperationW(ctypes.byref(request))
    if status or request.aborted:
        raise OSError('Recycle operation did not complete; check files before retrying')
