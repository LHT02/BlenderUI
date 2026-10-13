# SPDX-License-Identifier: GPL-2.0-or-later
"""ROOT-RUN ONLY: read actual Win10 tray control identity/semantics, never invoke."""
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import native_windows, notification_host, notification_uia_native as uia


def main():
    host, session, pending = notification_host.Host(private=True), None, []
    try:
        source = host._find_explorer()
        assert source
        host.user.GetDlgCtrlID.argtypes, host.user.GetDlgCtrlID.restype = [w.HWND], c.c_int
        session = uia.Session()
        pending, rows, visits, end = [(session.element(source[0]), 0, False)], [], 0, time.monotonic() + 4
        while pending and visits < 384 and time.monotonic() < end:
            element, depth, scope = pending.pop(0)
            visits += 1
            try:
                item = session.describe(element)
                if item['pid'] != source[1][0]:
                    continue
                scope = scope or item['class'] == 'TrayNotifyWnd'
                if scope and item['type'] == 50000:
                    pattern, _slot = session.action_pattern(element)
                    try:
                        rows.append({'name': item['name'], 'class': item['class'], 'id': item['id'],
                            'handle': item['handle'], 'ctrl_id': host.user.GetDlgCtrlID(item['handle']) if item['handle'] else 0,
                            'invoke': bool(pattern), 'expansion': session.expansion_state(element), 'rect': item['rect']})
                    finally:
                        uia.release(pattern)
                if depth < 12:
                    child = session.child(element)
                    try:
                        while child and child.value and len(pending) + visits < 384:
                            sibling = session.child(child, sibling=True)
                            pending.append((child, depth + 1, scope))
                            child = sibling
                    finally:
                        uia.release(child)
            finally:
                uia.release(element)
        print(json.dumps({'result': 'READONLY', 'controls': rows}, ensure_ascii=False, indent=2), flush=True)
    finally:
        for element, _depth, _scope in pending:
            uia.release(element)
        if session:
            session.close()
        host.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    main()
