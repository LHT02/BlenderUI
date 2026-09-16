# SPDX-License-Identifier: GPL-2.0-or-later
"""Draw the file browser's context menu, so a broken draw() shows up.

A Python exception inside a menu's `draw()` does not draw a broken entry - it
aborts the rest of the menu. Adding `icon='CUT'` to one entry, where this fork
has no `CUT` icon, therefore did not cost one icon: every entry after that line
disappeared, and the reported symptom was "the original menu is gone too".

Nothing here can assert what a menu contains, so this does the other half: it
opens the menu for real and leaves the traceback in stderr, where
`check_all.ps1` fails any check whose output contains one.

    BLUI.exe --factory-startup --enable-event-simulate \
        --python blui/tools/check_menu_draw.py
"""

import sys

import bpy

_state = {"step": 0}


def _step():
    step = _state["step"]
    _state["step"] += 1
    window = bpy.context.window_manager.windows[0]

    area = None
    region = None
    for a in window.screen.areas:
        if a.type == "FILE_BROWSER":
            area = a
            for r in a.regions:
                if r.type == "WINDOW":
                    region = r
            break

    if step == 0:
        if area is None or region is None:
            print("MENU: no file browser to right-click in")
            bpy.ops.wm.quit_blender()
            return None
        _state["x"] = region.x + region.width // 3
        _state["y"] = region.y + region.height - 80
        window.event_simulate(type="MOUSEMOVE", value="NOTHING",
                              x=_state["x"], y=_state["y"])
        return 0.4

    if step == 1:
        # Right-press opens FILEBROWSER_MT_context_menu, whose draw() is the
        # thing under test.
        window.event_simulate(type="RIGHTMOUSE", value="PRESS",
                              x=_state["x"], y=_state["y"])
        window.event_simulate(type="RIGHTMOUSE", value="RELEASE",
                              x=_state["x"], y=_state["y"])
        return 0.8

    if step == 2:
        # Walk into the "External" submenu too: its draw() is drawn from C but
        # its entries come from the shell, so it can fail on its own.
        window.event_simulate(type="ESC", value="PRESS", x=_state["x"], y=_state["y"])
        window.event_simulate(type="ESC", value="RELEASE", x=_state["x"], y=_state["y"])
        return 0.4

    print("MENU: RESULT context menu drawn")
    sys.stdout.flush()
    bpy.ops.wm.quit_blender()
    return None


def _wrapper():
    try:
        return _step()
    except Exception as exc:  # noqa: BLE001
        print("MENU: EXCEPTION %r" % (exc,))
        sys.stdout.flush()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(_wrapper, first_interval=2.0)
