# SPDX-License-Identifier: GPL-2.0-or-later
"""Click along the topbar menu strip and report any Python error.

Requires --enable-event-simulate.

Run with:
    BLUI.exe --enable-event-simulate --python tools/menu_click_test.py
"""

import bpy

WANTED = (
    "collada",
    "alembic",
    "usd",
    "io_gpencil",
    "io_wavefront_obj",
    "io_ply",
    "io_stl",
    "pugixml",
    "haru",
    "cycles",
)

_state = {"index": 0, "points": []}


def _report_build_options():
    opts = bpy.app.build_options
    for name in WANTED:
        if hasattr(opts, name):
            print("MENUTEST: build_options.%s = %r" % (name, getattr(opts, name)))
        else:
            print("MENUTEST: build_options.%s MISSING" % name)


def _tick():
    window = bpy.context.window_manager.windows[0]

    if not _state["points"]:
        _report_build_options()
        print("MENUTEST: window %dx%d" % (window.width, window.height))
        for area in window.screen.areas:
            pass
        try:
            for ga in window.global_areas:
                print(
                    "MENUTEST: global area %s xy=(%d,%d) wh=(%d,%d)"
                    % (ga.type, ga.x, ga.y, ga.width, ga.height)
                )
        except Exception as exc:  # noqa: BLE001
            print("MENUTEST: global_areas unavailable: %s" % (exc,))

        h = window.height
        top_y = h - 12
        # Sweep across the left half of the topbar where File/Edit/Render sit.
        _state["points"] = [(x, top_y) for x in range(20, 620, 40)]

    if _state["index"] >= len(_state["points"]):
        print("MENUTEST: finished without crashing")
        bpy.ops.wm.quit_blender()
        return None

    x, y = _state["points"][_state["index"]]
    _state["index"] += 1
    print("MENUTEST: click %d at (%d, %d)" % (_state["index"], x, y))
    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    window.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
    window.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)
    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y - 60)
    return 0.35


bpy.app.timers.register(_tick, first_interval=1.5)
