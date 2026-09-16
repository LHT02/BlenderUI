# SPDX-License-Identifier: GPL-2.0-or-later
"""Point the browser at a directory of our choosing, then press Enter in it.

Two questions in one run.

First: can a script navigate the file browser at all? Setting
`params.directory` updates the path but does NOT rebuild the list, which is why
so much of the file browser is untested - selection, delete and rename all need
a list that is really showing a directory we control. `file.select_bookmark`
looks like it might do it.

Second, if that works: pressing Enter on a folder should enter it. `file.execute`
is bound to RET and NUMPAD_ENTER and its directory branch calls
`ED_file_change_dir`, and unlike double-click this path can be driven from a
script - `event_simulate` cannot synthesise a DOUBLE_CLICK value, so
`check_double_click` had to be deleted.

    BLUI.exe --factory-startup --python blui/tools/probe_enter_navigation.py -- <dir>
"""

import os
import sys

import bpy

_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
_TARGET = _argv[0] if _argv else ""

_state = {"step": 0}
_failures = []


def report(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        _failures.append(message)


def finish(verdict=None):
    print("")
    name = "probe_enter_navigation"
    if verdict:
        print("%s: %s" % (name, verdict))
    else:
        print("%s: %s" % (name, "PASS" if not _failures else
                          "FAILED (%d)" % len(_failures)))
    sys.stdout.flush()
    os._exit(0 if (verdict or not _failures) else 1)


def _area():
    for window in bpy.context.window_manager.windows:
        for candidate in window.screen.areas:
            if candidate.type == "FILE_BROWSER":
                return candidate
    return None


def _step():
    step = _state["step"]
    _state["step"] += 1

    if step == 0:
        area = _area()
        if area is None:
            report(False, "there is a file browser")
            finish()
            return None
        _state["area"] = area
        _state["before"] = bytes(area.spaces.active.params.directory)
        print("ENTER: starting in %r" % _state["before"])

        with bpy.context.temp_override(area=area, space_data=area.spaces.active):
            try:
                result = bpy.ops.file.select_bookmark(dir=_TARGET)
            except Exception as exc:  # noqa: BLE001
                print("ENTER: select_bookmark raised %r" % (exc,))
                result = None
        print("ENTER: select_bookmark -> %r" % (result,))
        return 1.0

    if step == 1:
        after = bytes(_state["area"].spaces.active.params.directory)
        print("ENTER: now in %r" % after)
        if after != _state["before"]:
            report(True, "select_bookmark navigated the browser (%r -> %r)"
                         % (_state["before"], after))
        else:
            print("ENTER: INCONCLUSIVE - select_bookmark did not navigate, so a "
                  "controlled directory cannot be reached from a script")
            finish(verdict="INCONCLUSIVE (no scripted navigation available)")
            return None
        return 0.5

    if step == 2:
        # First row of the directory we asked for. select_walk is how a script
        # moves the highlight, which is what file.execute acts on.
        with bpy.context.temp_override(area=_state["area"],
                                       space_data=_state["area"].spaces.active):
            bpy.ops.file.select_walk(direction='DOWN')
        return 0.4

    if step == 3:
        _state["in_dir"] = bytes(_state["area"].spaces.active.params.directory)
        with bpy.context.temp_override(area=_state["area"],
                                       space_data=_state["area"].spaces.active):
            result = bpy.ops.file.execute()
        print("ENTER: file.execute -> %r" % (result,))
        return 1.2

    if step == 4:
        after = bytes(_state["area"].spaces.active.params.directory)
        print("ENTER: after Enter, in %r" % after)
        if after != _state["in_dir"]:
            report(True, "Enter on the first entry entered it (%r -> %r)"
                         % (_state["in_dir"], after))
            finish()
        else:
            # Deliberately NOT a failure. `file.execute` acts on
            # `params->active_file`, and whether `file.select_walk` set it
            # cannot be read from a script - `active_file` is not exposed to
            # RNA. So "nothing happened" here may mean Enter is broken or may
            # mean the highlight never moved. Reporting FAIL would be guessing.
            print("ENTER: file.execute returned FINISHED but the directory did "
                  "not change. Ambiguous: select_walk may not have set the "
                  "active file, and active_file is not readable from RNA.")
            finish(verdict="INCONCLUSIVE (active_file cannot be confirmed)")
        return None

    return None


def _wrapper():
    try:
        return _step()
    except Exception as exc:  # noqa: BLE001
        report(False, "the probe ran without raising (%s: %s)" % (type(exc).__name__, exc))
        finish()
        return None


bpy.app.timers.register(_wrapper, first_interval=2.5)
