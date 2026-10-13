# SPDX-License-Identifier: GPL-2.0-or-later
"""Second, minimal guardian covers an unexpected visibility-helper termination."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blui_desktop.taskbar_native import OwnerProcess, SessionLock, WindowsBars
from blui_desktop.taskbar_state import Guard, Journal


def run(directory, owner_pid, owner_started, helper_pid, helper_started):
    owner = helper = lock = None
    try:
        owner = OwnerProcess(owner_pid, owner_started)
        helper = OwnerProcess(helper_pid, helper_started)
        sys.stdout.write('READY\n')
        sys.stdout.flush()
        sys.stdout.close()
        while owner.alive() and helper.alive():
            time.sleep(.25)
        # Give the normal helper a short opportunity to restore first.
        for _ in range(12):
            if not helper.alive():
                break
            time.sleep(.1)
        try:
            lock = SessionLock()
        except RuntimeError:
            # A new guard always replays the old journal BEFORE enabling hiding.
            # Never compete with another active guard for taskbar ownership.
            return
        guard = Guard(WindowsBars(), Journal(directory))
        for _ in range(10):
            if guard.restore():
                break
            time.sleep(.1)
    finally:
        for resource in (owner, helper, lock):
            if resource:
                resource.close()


if __name__ == '__main__':
    if len(sys.argv) != 6:
        raise SystemExit(2)
    run(sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5])
