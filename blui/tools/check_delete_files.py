# SPDX-License-Identifier: GPL-2.0-or-later
"""Delete files in a directory the check controls.

`file.delete` had never been run end to end. The file list could not be pointed
at a directory from a script, so selection and deletion were out of reach - and
three operations in this file browser turned out to be silently doing nothing
precisely because nobody had been able to walk them.

`file.select_bookmark(dir=...)` fixes that, and this is the first check to use
it. It deletes inside a directory it created, and asserts the safety property
that makes that acceptable: `file.select_all` selects with `CHECK_FILES`, so
directories - including the `..` parent - are not selected.

Everything happens in steps with a delay between them, and that is not padding:
the first version called select_bookmark, select_all and delete back to back in
one function, and `file.delete` reported "context is incorrect" because the list
had not finished loading when select_all looked at it.

Run through `check_delete_files.cmd`.
"""

import os
import sys

import bpy

DST = os.environ.get("BLUI_DELETE_DIR", "")
FILES = [f for f in (os.environ.get("BLUI_DELETE_FILES", "") or "").split(",") if f]
KEEP_DIR = os.environ.get("BLUI_DELETE_KEEPDIR", "")

_state = {"step": 0, "area": None, "region": None}
_failures = []


def report(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        _failures.append(message)


def finish():
    print("")
    print("check_delete_files: %s" % ("PASS" if not _failures else
                                      "FAILED (%d)" % len(_failures)))
    sys.stdout.flush()
    os._exit(1 if _failures else 0)


def _override():
    return bpy.context.temp_override(area=_state["area"],
                                     region=_state["region"],
                                     space_data=_state["area"].spaces.active)


def _step():
    step = _state["step"]
    _state["step"] += 1

    if step == 0:
        print("BLUI delete files in a known directory")
        if not DST or not FILES or not KEEP_DIR:
            report(False, "BLUI_DELETE_DIR, BLUI_DELETE_FILES and BLUI_DELETE_KEEPDIR are set")
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

        report(_state["area"] is not None, "there is a file browser to delete in")
        # `region` is not optional: every file operator's poll goes through
        # ED_operator_file_browsing_active(), and without a region in the
        # override file.delete reports "context is incorrect" rather than running.
        report(_state["region"] is not None, "there is a window region to act in")
        if _state["area"] is None or _state["region"] is None:
            finish()
            return None

        for name in FILES:
            report(os.path.exists(os.path.join(DST, name)), "%s exists before" % name)
        report(os.path.isdir(KEEP_DIR), "the subdirectory exists before")
        return 0.3

    if step == 1:
        # The unlock: this puts the browser in a directory the check owns.
        # Setting params.directory alone updates the path but does not rebuild
        # the list, so selection would act on the wrong contents.
        with _override():
            result = bpy.ops.file.select_bookmark(dir=DST)
        report(result == {"FINISHED"}, "select_bookmark navigated there (got %r)" % (result,))
        landed = bytes(_state["area"].spaces.active.params.directory).decode(errors="replace")
        print("  browser is in %r" % landed)
        report(os.path.normcase(landed.rstrip("\\")) == os.path.normcase(DST.rstrip("\\")),
               "the browser is really in that directory")
        return 1.0   # let the list load before anything looks at it

    if step == 2:
        with _override():
            bpy.ops.file.select_all(action='SELECT')
        with _override():
            can = bpy.ops.file.delete.poll()
        report(can, "delete is available once something is selected")
        return 0.4

    if step == 3:
        with _override():
            result = bpy.ops.file.delete()
        print("  delete returned %r" % (result,))
        return 0.8

    for name in FILES:
        report(not os.path.exists(os.path.join(DST, name)), "%s was deleted" % name)

    # The safety property. If select_all had included `..`, this directory - or
    # the one above it - would be gone, which is why it is asserted, not assumed.
    report(os.path.isdir(DST), "the directory itself is still there")
    report(os.path.isdir(KEEP_DIR),
           "the subdirectory survived - select_all takes files, not directories")
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
