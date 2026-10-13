# SPDX-License-Identifier: GPL-2.0-or-later
"""Helper-only, explicit allowlisted system UI entry points; no foreign HWND actions."""
import ctypes as c
from ctypes import wintypes as w
import os
import subprocess
from . import notification_system as schema

KEYS = {'WIN': 0x5b, 'ALT': 0x12, 'SPACE': 0x20, 'A': 0x41, 'B': 0x42, 'D': 0x44, 'N': 0x4e}


class _Keyboard(c.Structure):
    _fields_ = [('key', w.WORD), ('scan', w.WORD), ('flags', w.DWORD), ('time', w.DWORD), ('extra', c.c_size_t)]


class _Mouse(c.Structure):
    _fields_ = [('x', w.LONG), ('y', w.LONG), ('data', w.DWORD), ('flags', w.DWORD),
                ('time', w.DWORD), ('extra', c.c_size_t)]


class _Union(c.Union):
    _fields_ = [('keyboard', _Keyboard), ('mouse', _Mouse)]


class _Input(c.Structure):
    _fields_ = [('kind', w.DWORD), ('data', _Union)]


def keyboard_plan(names):
    if not isinstance(names, list) or names not in (['WIN', 'A'], ['WIN', 'B'], ['WIN', 'N'],
                                                   ['WIN', 'SPACE'], ['WIN', 'ALT', 'D']):
        raise ValueError('Unsupported Windows shortcut')
    values = [KEYS[name] for name in names]
    return [(key, False) for key in values] + [(key, True) for key in reversed(values)]


def shortcut(names):
    user = c.WinDLL('user32', use_last_error=True, winmode=0x800)
    user.GetAsyncKeyState.argtypes, user.GetAsyncKeyState.restype = [c.c_int], c.c_short
    user.SendInput.argtypes, user.SendInput.restype = [w.UINT, c.POINTER(_Input), c.c_int], w.UINT
    if any(user.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5b, 0x5c)):
        raise RuntimeError('Release modifier keys before opening Windows system UI')
    plan = keyboard_plan(names)
    inputs = (_Input * len(plan))()
    for item, (key, up) in zip(inputs, plan):
        item.kind = 1
        item.data.keyboard = _Keyboard(key, 0, 2 if up else 0, 0, 0)
    sent = user.SendInput(len(inputs), inputs, c.sizeof(_Input))
    if sent != len(inputs):
        # Release only keys this explicitly requested shortcut may have pressed;
        # pre-existing modifier presses were rejected before any injection.
        releases = (_Input * len(names))()
        for item, name in zip(releases, reversed(names)):
            item.kind, item.data.keyboard = 1, _Keyboard(KEYS[name], 0, 2, 0, 0)
        user.SendInput(len(releases), releases, c.sizeof(_Input))
        raise OSError('Windows refused the system shortcut')


def action(key, event, *, private=False):
    if private or os.name != 'nt':
        raise ValueError('System UI actions are unavailable in a private notification test')
    request = schema.request(key, event, schema.build_number())
    if request['kind'] == 'URI':
        try:
            os.startfile(request['value'])
        except OSError:
            # The network flyout URI is version dependent. Explicit
            # fallback goes to its fixed documented settings page, not a command.
            if key != 'NETWORK' or request['value'] == schema.SETTINGS['NETWORK']:
                raise
            os.startfile(schema.SETTINGS['NETWORK'])
    elif request['kind'] == 'KEYS':
        shortcut(request['value'])
    else:
        kernel = c.WinDLL('kernel32', use_last_error=True, winmode=0x800)
        kernel.GetSystemDirectoryW.argtypes, kernel.GetSystemDirectoryW.restype = [w.LPWSTR, w.UINT], w.UINT
        directory = c.create_unicode_buffer(32768)
        if not 0 < kernel.GetSystemDirectoryW(directory, len(directory)) < len(directory):
            raise OSError('Windows system directory is unavailable')
        subprocess.Popen([os.path.join(directory.value, 'sndvol.exe')],
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return True
