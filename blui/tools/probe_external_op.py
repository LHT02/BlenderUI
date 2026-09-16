# SPDX-License-Identifier: GPL-2.0-or-later
"""Time an external operation, to catch one that blocks the UI.

Reported: "External -> Open Folder" freezes BLUI. `BLI_windows_external_operation_execute()`
calls `ShellExecuteExW` on the main thread, and `ShellExecuteEx` is documented to
wait on a GUI thread unless `SEE_MASK_ASYNCOK` is set - so a verb that goes
through DDE can block the whole application with no timeout and no message.

This measures it instead of arguing about it. Exits non-zero if the call took
longer than the budget, so the freeze is reproducible from a script.

    BLUI.exe --factory-startup --python blui/tools/probe_external_op.py -- <path> <OP>
"""

import sys
import time

import bpy

_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
_path = _argv[0] if _argv else "C:\\Windows"
_op = _argv[1] if len(_argv) > 1 else "FOLDER_OPEN"
_BUDGET_S = 3.0


def _run():
    print("EXTOP: %s on %r" % (_op, _path))
    sys.stdout.flush()

    started = time.time()
    result = None
    error = None
    try:
        result = bpy.ops.file.external_operation(filepath=_path, operation=_op)
    except Exception as exc:  # noqa: BLE001
        error = exc
    elapsed = time.time() - started

    print("EXTOP: returned %r in %.2fs (error=%r)" % (result, elapsed, error))
    slow = elapsed > _BUDGET_S
    print("EXTOP: RESULT %s" % ("BLOCKED" if slow else "OK"))
    sys.stdout.flush()
    # A blocked call may still be inside the shell; leave by force.
    import os
    os._exit(1 if slow else 0)
    return None


bpy.app.timers.register(_run, first_interval=2.0)
