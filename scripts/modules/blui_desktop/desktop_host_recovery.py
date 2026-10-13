# SPDX-License-Identifier: GPL-2.0-or-later
"""Second guardian: helper death, owner death or stalled helper restores original desktop."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blui_desktop.desktop_host_native import AbortEvent, DesktopWindows, OwnerProcess, SessionWitness
from blui_desktop.desktop_host_state import Guard, Journal, recovery_snapshot


def run(directory, nonce, owner_pid, owner_started, helper_pid, helper_started):
    owner = helper = abort = witness = None
    eof = threading.Event()
    lock = threading.Lock()
    heartbeat = [time.monotonic()]
    def reader():
        try:
            while True:
                line = sys.stdin.buffer.readline(33)
                if line != b'heartbeat\n':
                    break
                with lock:
                    heartbeat[0] = time.monotonic()
        finally:
            eof.set()
    try:
        owner = OwnerProcess(owner_pid, owner_started)
        helper = OwnerProcess(helper_pid, helper_started)
        witness = SessionWitness()
        abort = AbortEvent(nonce)
        journal = Journal(directory)
        backend = DesktopWindows()
        threading.Thread(target=reader, name='BLUI desktop recovery heartbeat', daemon=True).start()
        sys.stdout.buffer.write(b'READY\n')
        sys.stdout.buffer.flush()
        while owner.alive() and helper.alive() and not eof.is_set():
            with lock:
                last_seen = heartbeat[0]
            if time.monotonic() - last_seen > 15:
                break
            time.sleep(.2)
        abort.set()  # Stop attachment BEFORE replaying the journal, including a hung helper.
        # A guardian can never apply a newer service's journal or reusable HWND.
        for _ in range(30):
            value = recovery_snapshot(journal, nonce)
            if value is None or not value['shell'] and not value['canvases']:
                break
            guard = Guard(backend, journal, nonce)
            if guard.value['nonce'] != nonce:
                break
            if guard.restore():
                break
            time.sleep(.1)
    finally:
        for resource in (abort, helper, owner, witness):
            if resource:
                resource.close()


if __name__ == '__main__':
    if len(sys.argv) != 7:
        raise SystemExit(2)
    try:
        run(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], int(sys.argv[5]), sys.argv[6])
    finally:
        # A daemon readline must not deadlock CPython finalization after recovery.
        os._exit(0)
