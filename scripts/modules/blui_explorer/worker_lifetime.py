# SPDX-License-Identifier: GPL-2.0-or-later
"""Disposable Windows helpers stop when their exact spawning process exits.

Never use this for taskbar recovery/watchdog processes: those must outlive BLUI
long enough to restore the original system taskbar.
"""
import ctypes
from ctypes import wintypes
import os
import threading


def _wait(kernel, handle):
    try:
        if kernel.WaitForSingleObject(handle, 0xffffffff) == 0:
            os._exit(0)  # Only this disposable helper; never signal or kill the parent.
    finally:
        kernel.CloseHandle(handle)


def start():
    if os.name != 'nt':
        return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    parent = os.getppid()
    if not 0 < parent <= 0xffffffff or parent == os.getpid():
        return False
    # This immutable HANDLE keeps the original parent identity even after PID reuse.
    handle = kernel.OpenProcess(0x00100000, False, parent)  # SYNCHRONIZE, no mutation rights.
    if not handle:
        return False
    try:
        threading.Thread(target=_wait, args=(kernel, handle), daemon=True,
                         name='BLUI disposable helper owner').start()
    except Exception:
        kernel.CloseHandle(handle)
        raise
    return True
