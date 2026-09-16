# SPDX-License-Identifier: GPL-2.0-or-later
"""Create a window when none is open - the tray's path.

    BLUI.exe --factory-startup --python blui/tools/check_window_new_without_window.py

Every other window check starts from a window. This one does not, because that
is the case that broke: BLUI keeps running after the last window is closed (the
tray owns it), and a tray entry then asks for a component with no window to copy
from. `wm.window_new` takes a different branch there - `wm_window_new()` instead
of `wm_window_copy()` - and that branch was producing a window with no scene, no
view layer and no workspace, which killed the process on the first draw.

Nothing in the suite could see it: `check_component_window.py` always has a
window to start from, so it only ever exercises the copy branch.

The result is written to a log file as well as stdout, and for a reason: the
script has to close its own window to reach the interesting state, so if the
process dies there, stdout goes with it. The log is what is left.

Falsify-tested, and the result is worth keeping. Removing the single line
`win_fresh->scene = scene;` from `wm_window_new_exec()` makes this check report

    FAIL  the new window has a scene

and then the process dies with `EXCEPTION_ACCESS_VIOLATION`, exit code 11. Both
halves matter: the assertion says which property broke, and the crash is the
same abrupt disappearance a user sees when the tray opens a window. That is the
diagnosis in 434dc94 confirmed by experiment rather than by reading.
"""

import os
import sys
import tempfile

import bpy

LOG_PATH = os.path.join(tempfile.gettempdir(), "blui_no_window_check.log")
MINIMUM_WINDOWS = 1

_failures = []


def _log(message):
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def report(ok, message):
    line = ("  PASS  " if ok else "  FAIL  ") + message
    print(line)
    _log(line)
    if not ok:
        _failures.append(message)


def finish():
    print("")
    print("check_window_new_without_window: %s" % ("PASS" if not _failures else
                                                   "FAILED (%d)" % len(_failures)))
    sys.stdout.flush()
    _log("check_window_new_without_window: %s" % ("PASS" if not _failures else
                                                  "FAILED (%d)" % len(_failures)))
    os._exit(1 if _failures else 0)


def main():
    print("BLUI window creation with no window open")

    window_manager = bpy.context.window_manager
    report(len(window_manager.windows) >= MINIMUM_WINDOWS,
           "there is a window to start from (%d)" % len(window_manager.windows))

    # Close everything. The process is expected to stay alive with none open.
    for window in list(window_manager.windows):
        try:
            with bpy.context.temp_override(window=window):
                bpy.ops.wm.window_close()
        except Exception as exc:  # noqa: BLE001
            report(False, "closing a window raised %s: %s" % (type(exc).__name__, exc))

    report(len(window_manager.windows) == 0,
           "every window is closed (%d left)" % len(window_manager.windows))


def reopen():
    """Runs with no window open - the tray's situation."""
    window_manager = bpy.context.window_manager
    report(len(window_manager.windows) == 0,
           "still no window before asking for one")

    result = None
    try:
        result = bpy.ops.wm.window_new(workspace="Settings")
    except Exception as exc:  # noqa: BLE001
        report(False, "window_new with no window open raised %s: %s"
               % (type(exc).__name__, exc))
        return None

    report(result == {"FINISHED"}, "window_new returned FINISHED (got %r)" % (result,))
    report(len(window_manager.windows) == 1,
           "exactly one window exists again (%d)" % len(window_manager.windows))

    if window_manager.windows:
        window = window_manager.windows[0]
        report(window.screen is not None, "the new window has a screen")
        report(window.workspace is not None, "the new window has a workspace")
        report(window.scene is not None, "the new window has a scene")
        report(window.workspace is not None and window.workspace.name == "Settings",
               "the new window is on the component that was asked for")
    return None


def bad_component():
    """Ask for a component that does not exist, still with nothing open.

    This used to return FINISHED and produce nothing at all, so a stale tray
    entry looked exactly like a dead one. The window is what matters; the report
    naming the missing component is there for whoever can see reports.
    """
    window_manager = bpy.context.window_manager

    for window in list(window_manager.windows):
        with bpy.context.temp_override(window=window):
            bpy.ops.wm.window_close()
    report(len(window_manager.windows) == 0,
           "back to no windows before the bad request (%d)" % len(window_manager.windows))

    result = None
    try:
        result = bpy.ops.wm.window_new(workspace="BLUI_NoSuchComponent")
    except Exception as exc:  # noqa: BLE001
        report(False, "an unknown component raised %s: %s" % (type(exc).__name__, exc))
        return None

    report(result == {"FINISHED"}, "an unknown component returns FINISHED (got %r)" % (result,))
    report(len(window_manager.windows) == 1,
           "an unknown component still opens a window (%d)" % len(window_manager.windows))

    if window_manager.windows:
        window = window_manager.windows[0]
        report(window.screen is not None, "that window has a screen")
        report(window.workspace is not None, "that window fell back to some workspace")
    return None


# Reaching this line at all is half the test.
if bpy.app.background:
    print("check_window_new_without_window: SKIP (needs a window; do not pass --background)")
    sys.exit(0)

if os.path.exists(LOG_PATH):
    os.remove(LOG_PATH)
_log("start")

main()

bpy.app.timers.register(reopen, first_interval=1.5)
bpy.app.timers.register(bad_component, first_interval=3.0)
bpy.app.timers.register(finish, first_interval=5.0)
