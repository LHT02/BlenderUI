# SPDX-License-Identifier: GPL-2.0-or-later
"""Paste files from the system clipboard - the operator, not just the transport.

Run through `check_clipboard_paste.cmd`, which puts a real file list on the
clipboard first; nothing inside BLUI can set it, because a copy needs a file
selected and the file list cannot be driven from a script.

`dragsource_selftest.exe` covers the CF_HDROP payload and the round trip through
GHOST. What it cannot cover is the half above it: the operator collecting from
`params->dir`, calling BLI_copy, and the file turning up on disk.
"""

import os
import sys

import bpy

DST = os.environ.get("BLUI_PASTE_DST", "")
NAME = os.environ.get("BLUI_PASTE_NAME", "")

_failures = []


def report(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        _failures.append(message)


def finish():
    print("")
    print("check_clipboard_paste: %s" % ("PASS" if not _failures else
                                         "FAILED (%d)" % len(_failures)))
    sys.stdout.flush()
    os._exit(1 if _failures else 0)


def run():
    print("BLUI paste from the system clipboard")

    if bpy.app.background:
        print("check_clipboard_paste: SKIP (needs a window)")
        sys.exit(0)

    if not DST or not NAME:
        report(False, "BLUI_PASTE_DST and BLUI_PASTE_NAME are set")
        return

    target = os.path.join(DST, NAME)
    report(not os.path.exists(target), "the destination is empty to begin with")

    area = None
    for window in bpy.context.window_manager.windows:
        for candidate in window.screen.areas:
            if candidate.type == "FILE_BROWSER":
                area = candidate
                break
        if area is not None:
            break

    report(area is not None, "there is a file browser to paste into")
    if area is None:
        return

    # Paste reads params->dir rather than the file list, which is why this is
    # drivable from a script when a copy is not.
    area.spaces.active.params.directory = DST.encode()

    with bpy.context.temp_override(area=area, space_data=area.spaces.active):
        result = bpy.ops.file.clipboard_paste()

    report(result == {"FINISHED"}, "clipboard_paste returned FINISHED (got %r)" % (result,))
    report(os.path.exists(target), "the file is on disk afterwards (%s)" % target)

    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as handle:
            body = handle.read()
        report("paste" in body, "it has the contents of the original")


def guarded_run():
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        report(False, "the check ran without raising (%s: %s)" % (type(exc).__name__, exc))
    finish()


# Deferred rather than called inline, and that is not cosmetic: running this at
# script load crashed with an access violation. The operator needs the event loop
# to be running and the file browser's list to exist, and neither is true while
# the startup script is still executing. A timer waits for the state a user's
# click would find.
bpy.app.timers.register(guarded_run, first_interval=1.0)
