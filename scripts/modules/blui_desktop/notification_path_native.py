# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only normalization of Explorer NOTIFYITEM executable path forms.

Explorer may abbreviate known folders as {KNOWNFOLDERID}\\relative.exe. The
abbreviation is metadata, not an arbitrary command, and must be resolved before
comparing with QueryFullProcessImageName's actual owning-process executable.
"""
import ctypes as c
from ctypes import wintypes as w
import ntpath
import os
import re
from .notification_uia_native import GUID, HRESULT, checked

FOLDER = re.compile(r'^(?:::)?\{([0-9a-fA-F-]{36})\}[\\/](.+)$')


def form(value):
    if not value:
        return 'EMPTY'
    if FOLDER.fullmatch(value):
        return 'KNOWN_FOLDER'
    if '%' in value:
        return 'ENVIRONMENT'
    if value.startswith(('\\\\?\\', '\\??\\')):
        return 'NT_PREFIX'
    if ntpath.isabs(value):
        return 'ABSOLUTE'
    return 'RELATIVE'


def expand(value, folder_path=None):
    if not isinstance(value, str) or len(value) > 32768 or '\0' in value:
        raise ValueError('Invalid notification executable metadata')
    value = os.path.expandvars(value)
    match = FOLDER.fullmatch(value)
    if match:
        if folder_path is None:
            raise ValueError('Known-folder metadata needs a native resolver')
        suffix = match[2].replace('/', '\\')
        if ntpath.isabs(suffix) or any(part == '..' for part in suffix.split('\\')):
            raise ValueError('Invalid known-folder executable suffix')
        value = ntpath.join(folder_path(match[1]), suffix)
    if value.startswith('\\??\\'):
        value = value[4:]
    if value.startswith('\\\\?\\UNC\\'):
        value = '\\\\' + value[8:]
    elif value.startswith('\\\\?\\'):
        value = value[4:]
    return ntpath.normcase(ntpath.normpath(value))


class Resolver:
    def __init__(self):
        self.folders = {}
        self.shell = c.WinDLL('shell32', use_last_error=True, winmode=0x800)
        self.ole = c.WinDLL('ole32', use_last_error=True, winmode=0x800)
        self.kernel = c.WinDLL('kernel32', use_last_error=True, winmode=0x800)
        self.shell.SHGetKnownFolderPath.argtypes = [c.POINTER(GUID), w.DWORD, w.HANDLE, c.POINTER(c.c_void_p)]
        self.shell.SHGetKnownFolderPath.restype = HRESULT
        self.ole.CoTaskMemFree.argtypes, self.ole.CoTaskMemFree.restype = [c.c_void_p], None
        self.kernel.GetLongPathNameW.argtypes, self.kernel.GetLongPathNameW.restype = [w.LPCWSTR, w.LPWSTR, w.DWORD], w.DWORD

    def folder(self, identifier):
        if identifier not in self.folders:
            pointer = c.c_void_p()
            checked(self.shell.SHGetKnownFolderPath(c.byref(GUID.from_text(identifier)), 0, None, c.byref(pointer)))
            try:
                self.folders[identifier] = c.wstring_at(pointer)
            finally:
                self.ole.CoTaskMemFree(pointer)
        return self.folders[identifier]

    def normalize(self, value):
        result = expand(value, self.folder)
        # Do not query a network path from shell metadata. A local owning process
        # can be compared without introducing unbounded UNC provider delays.
        if result.startswith('\\\\') or not ntpath.isabs(result):
            return result
        buffer = c.create_unicode_buffer(32768)
        count = self.kernel.GetLongPathNameW(result, buffer, len(buffer))
        return expand(buffer.value) if 0 < count < len(buffer) else result
