# SPDX-License-Identifier: GPL-2.0-or-later
"""Create a folder, in a directory the check controls.

`file.directory_new` had never been run. It is another operation the file list
could not be pointed at before `file.select_bookmark(dir=...)`, and this file
browser has already produced three operations that were silently doing nothing,
so "it looks fine in the menu" is not evidence.

`confirm=False` is what makes it scriptable: with confirmation on, the operator
starts an inline rename, which is a modal edit box and not something a script
can finish. So this tests the create half, which is the half that has to work
before the rename half matters.

Run through `check_new_folder.cmd`.
"""

import os
import sys

import bpy

DST = os.environ.get("BLUI_NEWFOLDER_DIR", "")

_state = {"step": 0, "area": None, "region": None, "before": None}
_failures = []


def report(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        _failures.append(message)


def finish():
    print("")
    print("check_new_folder: %s" % ("PASS" if not _failures else
                                    "FAILED (%d)" % len(_failures)))
    sys.stdout.flush()
    os._exit(1 if _failures else 0)


def _override():
    return bpy.context.temp_override(area=_state["area"],
                                     region=_state["region"],
                                     space_data=_state["area"].spaces.active)


def _subdirs():
    try:
        return sorted(e.name for e in os.scandir(DST) if e.is_dir())
    except OSError:
        return []


def _step():
    step = _state["step"]
    _state["step"] += 1

    if step == 0:
        print("BLUI create a folder")
        if not DST:
            report(False, "BLUI_NEWFOLDER_DIR is set")
            finish()
            return None

        for window in bpy.context.window_manager.windows:
            for candidate in window.screen.areas:
                if candidate.type == "FILE_BROWSER":
                    _state["area"] = candidate
                    for candidate_region in candidate.regions:
                        if candidate_region.type == "WINDOW":
                            _state["region"] = candidate_region
                    break
            if _state["area"] is not None:
                break

        report(_state["area"] is not None, "there is a file browser")
        report(_state["region"] is not None, "there is a window region")
        if _state["area"] is None or _state["region"] is None:
            finish()
            return None

        _state["before"] = _subdirs()
        print("  folders before: %r" % (_state["before"],))
        report(_state["before"] == [], "the directory starts empty")
        return 0.3

    if step == 1:
        with _override():
            result = bpy.ops.file.select_bookmark(dir=DST)
        report(result == {"FINISHED"}, "select_bookmark navigated there (got %r)" % (result,))
        return 1.0   # the list has to finish loading before it is acted on

    if step == 2:
        with _override():
            can = bpy.ops.file.directory_new.poll()
        report(can, "directory_new is available")
        return 0.3

    if step == 3:
        with _override():
            result = bpy.ops.file.directory_new(confirm=False)
        print("  directory_new returned %r" % (result,))
        return 1.0   # the folder is created through the file list's job queue

    after = _subdirs()
    print("  folders after: %r" % (after,))
    report(len(after) == 1, "exactly one folder was created (got %r)" % (after,))
    report(os.path.isdir(DST), "the directory itself is still there")
    finish()
    return None


def _wrapper():
    try:
        return _step()
    except Exception as exc:  # noqa: BLE001
        report(False, "the check ran without raising (%s: %s)" % (type(exc).__name__, exc))
        finish()
        return None


bpy.app.timers.register(_wrapper, first_interval=1.2)
