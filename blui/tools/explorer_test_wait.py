# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded completion checks for the asynchronous file operators."""
import time
import bpy
from bl_operators import blui_file


def when_idle(verify, report, finish):
    deadline = time.monotonic() + 30
    def poll():
        try:
            if blui_file._jobs:
                if time.monotonic() > deadline:
                    raise TimeoutError('File task did not finish in 30 seconds')
                return 0.1
            if verify() is True:  # Another asynchronous assertion was scheduled.
                return None
        except Exception as exc:
            report(False, str(exc))
        finish()
        return None
    bpy.app.timers.register(poll, first_interval=0.15)
