# SPDX-License-Identifier: GPL-2.0-or-later
"""Drive the real shell menu popup, then let a helper process dismiss it.

Every other test of this feature stops short of `TrackPopupMenu`: the self test
stops at `QueryContextMenu`, and a script cannot press a menu that blocks the
thread it is running on. So the one step the user actually performs - the menu
appearing - had never been exercised.

This runs the operator for real. Because `TrackPopupMenu` runs its own modal
loop on the main thread, the dismissal has to come from outside the process:
start this first, then send Escape from a second process after a few seconds.

    BLUI.exe --factory-startup --enable-event-simulate \
        --python blui/tools/probe_shell_menu_popup.py

Read %TEMP%\\blui_shellmenu.log afterwards for what the popup did internally.
"""

import os
import sys

import bpy

_state = {"step": 0}


def _file_browser(window):
    for area in window.screen.areas:
        if area.type == "FILE_BROWSER":
            for region in area.regions:
                if region.type == "WINDOW":
                    return area, region
    return None, None


def _step():
    step = _state["step"]
    _state["step"] += 1
    window = bpy.context.window_manager.windows[0]
    area, region = _file_browser(window)

    if step == 0:
        if area is None:
            print("POPUP: RESULT NO-FILE-BROWSER")
            bpy.ops.wm.quit_blender()
            return None
        _state["x"] = region.x + region.width // 2
        _state["y"] = region.y + region.height - 60
        window.event_simulate(type="MOUSEMOVE", value="NOTHING",
                              x=_state["x"], y=_state["y"])
        return 0.4

    if step == 1:
        # Right-press first: this is what makes a file active, the same way a
        # person does it before choosing the menu entry.
        window.event_simulate(type="RIGHTMOUSE", value="PRESS",
                              x=_state["x"], y=_state["y"])
        window.event_simulate(type="RIGHTMOUSE", value="RELEASE",
                              x=_state["x"], y=_state["y"])
        window.event_simulate(type="ESC", value="PRESS", x=_state["x"], y=_state["y"])
        window.event_simulate(type="ESC", value="RELEASE", x=_state["x"], y=_state["y"])
        return 0.5

    if step == 2:
        print("POPUP: invoking file.shell_context_menu (blocks until dismissed)")
        sys.stdout.flush()
        try:
            with bpy.context.temp_override(area=area, region=region, window=window):
                # INVOKE_DEFAULT is what a menu entry uses; a bare call is
                # EXEC_DEFAULT, and this operator has no exec callback at all,
                # so a bare call never reaches the code under test.
                result = bpy.ops.file.shell_context_menu('INVOKE_DEFAULT')
            print("POPUP: operator returned %r" % (result,))
        except Exception as exc:  # noqa: BLE001
            print("POPUP: operator raised %r" % (exc,))
        sys.stdout.flush()
        return 0.3

    print("POPUP: RESULT done")
    sys.stdout.flush()
    os._exit(0)
    return None


def _wrapper():
    try:
        return _step()
    except Exception as exc:  # noqa: BLE001
        print("POPUP: EXCEPTION %r" % (exc,))
        sys.stdout.flush()
        os._exit(0)
        return None


bpy.app.timers.register(_wrapper, first_interval=2.0)
