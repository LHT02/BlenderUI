# SPDX-License-Identifier: GPL-2.0-or-later
"""Dropping a file into the browser copies it into the folder on screen.

GHOST already registers an OLE drop target and hands Blender every dropped
filename, so the gesture arrived - but `FILE_OT_filepath_drop` only ever set the
filepath, which is right in a save dialog and useless in a file manager: dragging
a file in from Explorer did nothing at all.

The OLE delivery itself cannot be driven from a script, so this drives the
operator the dropbox calls, with the same context a drop would give it.

Run through `check_drop_into_folder.cmd`.
"""

import os
import sys

import bpy

SRC = os.environ.get("BLUI_DROP_SRC", "")
DST = os.environ.get("BLUI_DROP_DST", "")
NAME = os.environ.get("BLUI_DROP_NAME", "")

_failures = []


def report(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        _failures.append(message)


def finish():
    print("")
    print("check_drop_into_folder: %s" % ("PASS" if not _failures else
                                          "FAILED (%d)" % len(_failures)))
    sys.stdout.flush()
    os._exit(1 if _failures else 0)


def run():
    print("BLUI drop a file into the folder on screen")

    if bpy.app.background:
        print("check_drop_into_folder: SKIP (needs a window)")
        sys.exit(0)

    if not SRC or not DST or not NAME:
        report(False, "BLUI_DROP_SRC, BLUI_DROP_DST and BLUI_DROP_NAME are set")
        return

    target = os.path.join(DST, NAME)
    report(os.path.exists(SRC), "the dropped file exists")
    report(not os.path.exists(target), "the destination is empty to begin with")

    area = None
    for window in bpy.context.window_manager.windows:
        for candidate in window.screen.areas:
            if candidate.type == "FILE_BROWSER":
                area = candidate
                break
        if area is not None:
            break
    report(area is not None, "there is a file browser to drop into")
    if area is None:
        return

    area.spaces.active.params.directory = DST.encode()

    with bpy.context.temp_override(area=area, space_data=area.spaces.active):
        result = bpy.ops.file.filepath_drop(filepath=SRC)

    report(result == {"FINISHED"}, "filepath_drop returned FINISHED (got %r)" % (result,))
    report(os.path.exists(target), "the dropped file was copied here (%s)" % target)
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as handle:
            report("drop probe" in handle.read(), "it has the contents of the original")
        # Dropping the same name again must not replace what is here.
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("already here\n")
        with bpy.context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.file.filepath_drop(filepath=SRC)
        with open(target, "r", encoding="utf-8") as handle:
            report("already here" in handle.read(),
                   "a second drop of the same name did not overwrite it")


def guarded_run():
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        report(False, "the check ran without raising (%s: %s)" % (type(exc).__name__, exc))
    finish()


bpy.app.timers.register(guarded_run, first_interval=1.2)
