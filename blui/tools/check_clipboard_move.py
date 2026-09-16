# SPDX-License-Identifier: GPL-2.0-or-later
"""Cut and paste across volumes - the case a rename cannot do.

`BLI_rename` is `rename()`, which fails with EXDEV when the destination is on
another filesystem. Cutting a file on D: and pasting it into C: therefore did
nothing at all, and said nothing. The operator now falls back to copy-then-
delete; this is the check that it really moves the bytes and removes the
original.

Run through `check_clipboard_move.cmd`, which needs a source on a different
volume from the destination and puts it on the clipboard as a cut.
"""

import os
import sys

import bpy

DST = os.environ.get("BLUI_PASTE_DST", "")
NAME = os.environ.get("BLUI_PASTE_NAME", "")
SRC = os.environ.get("BLUI_MOVE_SRC", "")
SRCDIR = os.environ.get("BLUI_MOVE_DIR", "")

_failures = []


def report(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        _failures.append(message)


def finish():
    print("")
    print("check_clipboard_move: %s" % ("PASS" if not _failures else
                                        "FAILED (%d)" % len(_failures)))
    sys.stdout.flush()
    os._exit(1 if _failures else 0)


def run():
    print("BLUI cut and paste across volumes")

    if bpy.app.background:
        print("check_clipboard_move: SKIP (needs a window)")
        sys.exit(0)

    if not DST or not NAME or not SRC:
        report(False, "BLUI_PASTE_DST, BLUI_PASTE_NAME and BLUI_MOVE_SRC are set")
        return

    source_volume = os.path.splitdrive(SRC)[0].upper()
    dest_volume = os.path.splitdrive(DST)[0].upper()
    report(source_volume != dest_volume,
           "the source and destination are on different volumes (%s vs %s)"
           % (source_volume, dest_volume))
    report(os.path.exists(SRC), "the source file exists before the cut")
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

    area.spaces.active.params.directory = DST.encode()

    with bpy.context.temp_override(area=area, space_data=area.spaces.active):
        result = bpy.ops.file.clipboard_paste()

    report(result == {"FINISHED"}, "clipboard_paste returned FINISHED (got %r)" % (result,))
    report(os.path.exists(target), "the file arrived (%s)" % target)
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as handle:
            report("move probe" in handle.read(), "it has the contents of the original")
    # The half a rename would have got wrong: the original must be gone.
    report(not os.path.exists(SRC), "the original file is gone - the cut really moved it")

    # And a folder, which `BLI_copy` cannot do at all: it is `CopyFileW`, so
    # every folder paste used to do nothing.
    dir_target = os.path.join(DST, os.path.basename(SRCDIR)) if SRCDIR else ""
    report(bool(SRCDIR) and os.path.isdir(dir_target),
           "the folder arrived (%s)" % dir_target)
    if dir_target and os.path.isdir(dir_target):
        inner = os.path.join(dir_target, "inner.txt")
        report(os.path.exists(inner), "the file inside the folder came with it (%s)" % inner)
        if os.path.exists(inner):
            with open(inner, "r", encoding="utf-8") as handle:
                report("inner payload" in handle.read(), "the inner file has its contents")
    report(bool(SRCDIR) and not os.path.exists(SRCDIR),
           "the original folder is gone - the cut really moved the tree")


def guarded_run():
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        report(False, "the check ran without raising (%s: %s)" % (type(exc).__name__, exc))
    finish()


bpy.app.timers.register(guarded_run, first_interval=1.0)
