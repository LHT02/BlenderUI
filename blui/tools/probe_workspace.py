# SPDX-License-Identifier: GPL-2.0-or-later
"""Probe: can we retype an area and close areas with a context override?"""

import bpy


def dump(tag):
    ws = bpy.context.window.workspace
    for screen in ws.screens:
        print(
            "PROBE-%s ws=%r screen=%r areas=%s"
            % (tag, ws.name, screen.name, [a.type for a in screen.areas])
        )


def main():
    win = bpy.context.window
    ws = win.workspace
    dump("BEFORE")

    screen = win.screen
    view3d = next((a for a in screen.areas if a.type == "VIEW_3D"), None)
    print("PROBE-view3d %s" % (view3d,))
    if view3d is None:
        print("PROBE-NO-VIEW3D")
        return

    try:
        with bpy.context.temp_override(window=win, screen=screen, area=view3d):
            res = bpy.ops.screen.space_type_set_or_cycle(space_type="FILE_BROWSER")
        print("PROBE-retype result=%s" % (res,))
    except Exception as exc:  # noqa: BLE001
        print("PROBE-retype EXC %s" % (exc,))
    dump("AFTER-RETYPE")

    # Try closing a now-redundant area.
    props = next((a for a in screen.areas if a.type == "PROPERTIES"), None)
    if props is not None:
        try:
            with bpy.context.temp_override(window=win, screen=screen, area=props):
                res = bpy.ops.screen.area_close()
            print("PROBE-close result=%s" % (res,))
        except Exception as exc:  # noqa: BLE001
            print("PROBE-close EXC %s" % (exc,))
    dump("AFTER-CLOSE")
    print("PROBE-DONE")


main()
