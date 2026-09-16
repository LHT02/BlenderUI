# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolated STA shell host. Owns one menu until its client closes the session."""
import ctypes
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mailbox import publish, take
from shell_win32 import ShellMenu, pump, properties


def main():
    directory = Path(sys.argv[1])
    ctypes.OleDLL('ole32').CoInitializeEx(None, 2)
    menu = None
    serial = 1
    try:
        while directory.is_dir():
            pump()
            request = take(directory, 'request-%d.json' % serial)
            if request is None:
                time.sleep(0.02)
                continue
            reply = {'ok': False}
            try:
                op = request['op']
                if op == 'list':
                    if menu is not None:
                        raise ValueError('A helper owns exactly one menu session')
                    paths = [os.path.normpath(path) for path in request['paths']]
                    if len({os.path.normcase(os.path.dirname(p.rstrip('\\/'))) for p in paths}) != 1:
                        raise ValueError('Select items in the same folder')
                    menu = ShellMenu(paths)
                    reply['items'] = menu.items()
                elif op == 'expand':
                    reply['items'] = menu.items(request['node'])
                elif op == 'invoke':
                    menu.invoke(int(request['command']))
                elif op == 'properties':
                    properties(request['paths'][0])
                else:
                    raise ValueError('Unknown menu request')
                reply['ok'] = True
            except Exception as exc:
                reply['error'] = str(exc)
            publish(directory, 'reply-%d.json' % serial, reply)
            serial += 1
    finally:
        if menu is not None:
            menu.close()
        ctypes.OleDLL('ole32').CoUninitialize()


if __name__ == '__main__':
    main()
