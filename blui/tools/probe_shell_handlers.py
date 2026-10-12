# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only folder-menu diagnostics. Never invokes commands or changes registrations."""
import concurrent.futures
import ctypes as c
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import winreg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))


def child(path, clsid):
    from blui_explorer import shell_win32 as s
    s.ole.CoInitializeEx(None, 2)
    folder, data, init, menu = s.P(), s.P(), s.P(), s.P()
    absolute, parent_id = s.P(), s.P()
    handle = None
    started = time.monotonic()
    print('create', flush=True)
    create = s.api(s.ole, 'CoCreateInstance', s.HRESULT, c.POINTER(s.GUID), s.P,
                   s.w.DWORD, c.POINTER(s.GUID), c.POINTER(s.P))
    s.check(create(c.byref(s.GUID(clsid)), None, 1, c.byref(s.GUID(
        '000214e8-0000-0000-c000-000000000046')), c.byref(init)), 'Create handler')
    s.check(s.parse_name(path, None, c.byref(absolute), 0, None), 'Parse item')
    relative = s.P()
    s.check(s.bind_parent(absolute, c.byref(s.IID_FOLDER), c.byref(folder), c.byref(relative)), 'Parent')
    array = (s.P * 1)(relative.value)
    s.check(s.method(folder, 10, s.HRESULT, s.P, s.w.UINT, c.POINTER(s.P),
                     c.POINTER(s.GUID), s.P, c.POINTER(s.P))(
        folder, None, 1, array, c.byref(s.GUID('0000010e-0000-0000-c000-000000000046')),
        None, c.byref(data)), 'Data object')
    s.check(s.parse_name(os.path.dirname(path), None, c.byref(parent_id), 0, None), 'Parse parent')
    print('initialize', flush=True)
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, 'Directory') as key:
        s.check(s.method(init, 3, s.HRESULT, s.P, s.P, s.P)(init, parent_id, data, int(key)), 'Initialize')
    menu = s.query(init, s.IID_MENU)
    if not menu:
        raise RuntimeError('No IContextMenu')
    handle = s.create_menu()
    print('query', flush=True)
    s.check(s.method(menu, 3, s.HRESULT, s.P, s.w.UINT, s.w.UINT, s.w.UINT, s.w.UINT)(
        menu, handle, 0, 1, 0x7fff, 0x84), 'Query')
    print('ready %.3fs rows=%d' % (time.monotonic() - started, s.menu_count(handle)), flush=True)
    # Avoid unloading a third-party DLL after diagnostics; the child exits immediately.
    os._exit(0)


def registrations():
    seen = set()
    for group in ('Directory', 'Folder', 'AllFilesystemObjects'):
        try:
            key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, group + r'\shellex\ContextMenuHandlers')
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                name = winreg.EnumKey(key, i)
                with winreg.OpenKey(key, name) as handler:
                    try:
                        value = winreg.QueryValueEx(handler, '')[0]
                    except OSError:
                        value = ''
                clsid = next((v for v in (value, name) if re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}', v)), None)
                if clsid and clsid.lower() not in seen:
                    seen.add(clsid.lower())
                    yield group + '/' + name, clsid


def probe(path, registration):
    name, clsid = registration
    process = subprocess.Popen([sys.executable, '-u', __file__, '--child', path, clsid],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        output, _ = process.communicate(timeout=4)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        return name + ' TIMEOUT ' + output.strip().replace('\n', ' | ')
    return name + ' ' + output.strip().replace('\n', ' | ')


if __name__ == '__main__':
    if sys.argv[1] == '--child':
        try:
            child(sys.argv[2], sys.argv[3])
        except Exception as exc:
            print(str(exc), flush=True)
            os._exit(1)
    path = os.path.abspath(sys.argv[1])
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for output in pool.map(lambda registration: probe(path, registration), registrations()):
            print(output, flush=True)
