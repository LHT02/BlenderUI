# SPDX-License-Identifier: GPL-2.0-or-later
"""Dump the workspace / screen / area layout of the running BLUI instance.

Used while designing BLUI's own startup file: it shows exactly which areas a
screen is made of, how they are laid out, and which space each area holds.

Note: BLUI 3.6 embeds Python 3.10, which does not allow re-using the enclosing
quote type inside an f-string expression. Keep formatting plain.

Run with:
    BLUI.exe --python tools/dump_screens.py
"""

import bpy


def main():
    print("=== WORKSPACES ===")
    for ws in bpy.data.workspaces:
        print("workspace %r screens=%s" % (ws.name, [s.name for s in ws.screens]))
        for screen in ws.screens:
            for area in screen.areas:
                space_types = [s.type for s in area.spaces]
                print(
                    "    [%s] area %-14s xy=(%d,%d) wh=(%d,%d) spaces=%s"
                    % (
                        screen.name,
                        area.type,
                        area.x,
                        area.y,
                        area.width,
                        area.height,
                        space_types,
                    )
                )
    print("=== WINDOW ===")
    for win in bpy.context.window_manager.windows:
        print("window %r workspace=%r" % (win.screen.name, win.workspace.name))
    print("=== DONE ===")


main()
