# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolated Programs-folder enumeration, preference persistence and explicit launches.

Open-Shell is a design reference (MIT), not a copied/linked dependency:
https://github.com/Open-Shell/Open-Shell-Menu/tree/master/Src/StartMenu/StartMenuDLL
Unlike its optional command execution/search providers, BLUI's search only filters
the previously scanned program list. Nothing in this module imports bpy.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import stat
import time
import uuid
from . import model, start_menu_model as schema

_FOLDERS = {'user': 'A77F5D77-2E2B-44C3-A6A2-ABA601054A51',
            'common': '0139D44E-6AFE-49F2-8690-3DAFCAE6FFB8',
            'profile': '5E6C858F-0E22-4760-9AFE-EA3317B67173',
            'documents': 'FDD39AD0-238F-46AF-ADB4-6C85480369C7',
            'pictures': '33E28130-4E1E-4676-835A-98395C3BC3BB',
            'music': '4BD8D571-6D19-48D3-BE97-422220080E43',
            'downloads': '374DE290-123F-4565-9164-39C4925E467B'}
_REPARSE = 0x400
MAX_ENTRIES = 8192
MAX_DEPTH = 8
SCAN_SECONDS = 4


def known_folder(kind):
    if os.name != 'nt' or kind not in _FOLDERS:
        raise ValueError('Windows Programs folders are unavailable')
    shell, ole = ctypes.WinDLL('shell32', use_last_error=True), ctypes.WinDLL('ole32')
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_wchar_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(_FOLDERS[kind]).bytes_le)
    output = ctypes.c_wchar_p()
    try:
        # DONT_VERIFY follows configured redirection, without creating a missing folder.
        if shell.SHGetKnownFolderPath(ctypes.byref(guid), 0x4000, None, ctypes.byref(output)) or not output.value:
            raise OSError('Could not locate the Windows Programs folder')
        return output.value
    finally:
        if output:
            ole.CoTaskMemFree(output)


def _program_roots():
    roots = {}
    for source in ('user', 'common'):
        try:
            roots[source] = known_folder(source)
        except OSError:
            continue
    return roots


def _signature(info):
    return {'mtime_ns': info.st_mtime_ns, 'size': info.st_size,
            'device': info.st_dev, 'inode': info.st_ino}


def _reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & _REPARSE)


def _inside(root, path):
    root, path = os.path.normcase(os.path.realpath(root)), os.path.normcase(os.path.realpath(path))
    try:
        return os.path.commonpath((root, path)) == root and path != root
    except ValueError:
        return False


def scan_programs(roots=None, *, clock=time.monotonic):
    """Bounded recursive scan; no Shell extensions, .lnk resolution or junction traversal."""
    roots = _program_roots() if roots is None else roots
    if (not isinstance(roots, dict) or not set(roots) <= {'user', 'common'} or
            any(not isinstance(path, str) or not os.path.isabs(path) for path in roots.values())):
        raise ValueError('Invalid Windows Programs roots')
    rows, errors, visited, truncated = [], [], 0, False
    deadline = clock() + SCAN_SECONDS
    for source in ('user', 'common'):
        if source not in roots:
            continue
        root = os.path.abspath(roots[source])
        stack = [(root, 0)]
        while stack:
            if visited >= MAX_ENTRIES or len(rows) >= schema.MAX_APPS or clock() >= deadline:
                truncated = True
                break
            folder, depth = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        visited += 1
                        if visited > MAX_ENTRIES or len(rows) >= schema.MAX_APPS or clock() >= deadline:
                            truncated = True
                            break
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if _reparse(info):
                                continue
                            if stat.S_ISDIR(info.st_mode):
                                if depth < MAX_DEPTH:
                                    stack.append((entry.path, depth + 1))
                                else:
                                    truncated = True
                                continue
                            if not stat.S_ISREG(info.st_mode) or entry.name.rsplit('.', 1)[-1].lower() not in {'lnk', 'exe'}:
                                continue
                            if not _inside(root, entry.path):
                                continue
                            # On Windows, DirEntry.stat deliberately reports st_ino == 0;
                            # os.stat supplies the real file index required by launch validation.
                            info = os.stat(entry.path, follow_symlinks=False)
                            if _reparse(info) or not stat.S_ISREG(info.st_mode):
                                continue
                            relative = os.path.relpath(entry.path, root).replace('/', '\\')
                            row = {'id': schema.app_id(source, relative), 'source': source,
                                   'relative': relative, 'path': os.path.abspath(entry.path),
                                   'name': os.path.splitext(entry.name)[0],
                                   'group': os.path.dirname(relative.replace('\\', os.sep)).replace(os.sep, ' / '),
                                   'signature': _signature(info)}
                            rows.append(schema.program(row))
                        except (OSError, ValueError):
                            # A removed/inaccessible item must not discard an otherwise useful index.
                            continue
            except OSError as exc:
                if len(errors) < 32:
                    errors.append((source + ': ' + str(exc))[:1024].replace('\n', ' ').replace('\r', ' '))
        if visited >= MAX_ENTRIES or len(rows) >= schema.MAX_APPS or clock() >= deadline:
            truncated = True
            break
    rows.sort(key=lambda row: (schema.folded(row['name']), schema.folded(row['group']), row['source']))
    # The same physical file can be returned for both redirected roots. Prefer user scope.
    paths, unique = set(), []
    for row in sorted(rows, key=lambda row: row['source'] != 'user'):
        path = os.path.normcase(row['path'])
        if path not in paths:
            paths.add(path)
            unique.append(row)
    unique.sort(key=lambda row: (schema.folded(row['name']), schema.folded(row['group']), row['id']))
    return {'rows': unique, 'truncated': truncated, 'errors': errors}


def _state_path(directory):
    schema.text(directory, 32768, empty=False)
    if not os.path.isabs(directory):
        raise ValueError('Invalid Start menu configuration folder')
    return Path(directory) / 'start-menu.json'


def _read(target):
    with target.open('rb') as source:
        data = source.read(65537)
    if len(data) > 65536:
        raise ValueError('Start menu preferences are too large')
    return schema.state(json.loads(data.decode('utf-8')))


def load_state(directory):
    target = _state_path(directory)
    for candidate in (target, target.with_suffix('.bak')):
        try:
            return _read(candidate)
        except (OSError, ValueError, UnicodeError):
            pass
    return schema.empty_state()


def start_state(directory, value):
    value = schema.state(value)
    target = _state_path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    with model._save_lock(target):
        current = load_state(directory)
        if current['revision'] > value['revision']:
            raise ValueError('Start menu preferences changed; refresh the menu')
        if current['revision'] == value['revision'] and current != value:
            raise ValueError('Conflicting Start menu preferences; refresh the menu')
        if target.exists():
            try:
                previous = _read(target)
                model._publish(target.with_suffix('.bak'), json.dumps(previous).encode('utf-8'))
            except (OSError, ValueError, UnicodeError):
                pass  # A damaged main file must never replace the last valid backup.
        model._publish(target, json.dumps(value, ensure_ascii=False).encode('utf-8'))
    return True


def start_index(directory):
    return schema.validate_index(dict(load_state(directory), **scan_programs()))


def validated_target(value, roots=None):
    row = schema.program(value)
    roots = _program_roots() if roots is None else roots
    root = roots.get(row['source'])
    if not root:
        raise ValueError('The Windows Programs folder changed; refresh the menu')
    relative = row['relative'].replace('\\', os.sep)
    path = os.path.abspath(os.path.join(root, relative))
    if (os.path.normcase(path) != os.path.normcase(row['path']) or not _inside(root, path)):
        raise ValueError('The program moved outside the Programs folder; refresh the menu')
    ancestor = root
    for part in relative.split(os.sep):
        ancestor = os.path.join(ancestor, part)
        if _reparse(os.stat(ancestor, follow_symlinks=False)):
            raise ValueError('Start menu junction/link target changed; refresh the menu')
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or _signature(info) != row['signature']:
        raise ValueError('The program changed since indexing; refresh the menu')
    return path


@contextmanager
def _file_guard(path):
    """Deny concurrent write/delete while ShellExecute reads this explicitly selected link."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # READ_ATTRIBUTES alone does not participate in Windows file sharing checks.
    # GENERIC_READ + FILE_SHARE_READ permits Shell reads but denies mutation here.
    handle = kernel.CreateFileW(path, 0x80000000, 1, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def start_launch(value):
    if os.name != 'nt':
        raise RuntimeError('Starting Windows programs requires Windows')
    path = validated_target(value)
    with _file_guard(path):
        # Check identity again under the write/delete guard. No search or command text is used.
        validated_target(value)
        os.startfile(path, 'open')
    return True


def start_location(value):
    """Open only the containing Programs folder of an explicitly selected, rechecked app."""
    if os.name != 'nt':
        raise RuntimeError('Opening Windows program locations requires Windows')
    path = validated_target(value)
    with _file_guard(path):
        validated_target(value)
        os.startfile(os.path.dirname(path))
    return True


def _shutdown(restart):
    """User-confirmed shutdown without FORCE/FORCEIFHUNG, preserving Windows save prompts."""
    class Luid(ctypes.Structure):
        _fields_ = [('low', wintypes.DWORD), ('high', wintypes.LONG)]
    class Privilege(ctypes.Structure):
        _fields_ = [('count', wintypes.DWORD), ('luid', Luid), ('attributes', wintypes.DWORD)]
    kernel, security = ctypes.WinDLL('kernel32', use_last_error=True), ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(Luid)]
    security.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(Privilege),
                                             wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    token, privilege = wintypes.HANDLE(), Privilege()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x28, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        privilege.count, privilege.attributes = 1, 2
        if not security.LookupPrivilegeValueW(None, 'SeShutdownPrivilege', ctypes.byref(privilege.luid)):
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.set_last_error(0)
        if not security.AdjustTokenPrivileges(token, False, ctypes.byref(privilege), 0, None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.ExitWindowsEx.argtypes = [wintypes.UINT, wintypes.DWORD]
        if not user.ExitWindowsEx(2 if restart else 8, 0x80040000):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(token)


def start_system(action):
    if os.name != 'nt' or not isinstance(action, str) or action not in schema.SYSTEM_ACTIONS:
        raise ValueError('Unsupported Start menu system action')
    if action == 'FILES':
        os.startfile(known_folder('profile'))
    elif action in {'DOCUMENTS', 'PICTURES', 'MUSIC', 'DOWNLOADS'}:
        os.startfile(known_folder(action.lower()))
    elif action in {'COMPUTER', 'CONTROL_PANEL'}:
        os.startfile('shell:MyComputerFolder' if action == 'COMPUTER' else 'shell:ControlPanelFolder')
    elif action in {'SETTINGS', 'POWER_SETTINGS'}:
        os.startfile('ms-settings:' if action == 'SETTINGS' else 'ms-settings:powersleep')
    elif action == 'LOCK':
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.LockWorkStation.argtypes = []
        if not user.LockWorkStation():
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        _shutdown(action == 'RESTART')
    return True
