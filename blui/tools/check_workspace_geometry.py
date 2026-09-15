# SPDX-License-Identifier: GPL-2.0-or-later
"""Switch through every workspace and report the geometry of its main area.

Used to confirm that workspaces saved before the top bar and status bar were
removed expand to the full window once they are shown, rather than keeping the
offsets those bars used to occupy.

Run with:
    BLUI.exe --factory-startup --python blui/tools/check_workspace_geometry.py
"""

import bpy

_names = []
_index = {"i": 0}


def _tick():
    window = bpy.context.window

    if not _names:
        _names.extend(w.name for w in bpy.data.workspaces)
        print("GEOM: window %dx%d" % (window.width, window.height))

    if _index["i"] >= len(_names):
        print("GEOM: done")
        bpy.ops.wm.quit_blender()
        return None

    name = _names[_index["i"]]
    _index["i"] += 1
    for workspace in bpy.data.workspaces:
        if workspace.name == name:
            window.workspace = workspace
            break

    # Let the window lay the new screen out before reading it back.
    def _report():
        screen = bpy.context.window.screen
        for area in screen.areas:
            print(
                "GEOM: %-9s area=%-14s xy=(%d,%d) wh=(%dx%d)"
                % (name, area.type, area.x, area.y, area.width, area.height)
            )
        return None

    # Give the screen switch one extra event loop turn first.
    bpy.app.timers.register(_report, first_interval=0.05)
    return 0.25


bpy.app.timers.register(_tick, first_interval=0.6)
