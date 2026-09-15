# SPDX-License-Identifier: GPL-2.0-or-later
"""Drive BLUI with simulated mouse clicks to check for click-triggered crashes.

Requires the `--enable-event-simulate` command line flag.

Run with:
    BLUI.exe --enable-event-simulate --python tools/click_test.py

Clicks are spaced out over timer callbacks so each one is processed by its own
pass through the event loop, the way a real click is, rather than all landing in
the same batch.
"""

import bpy

_state = {"index": 0, "points": []}


def _tick():
    window = bpy.context.window_manager.windows[0]

    if not _state["points"]:
        w, h = window.width, window.height
        print("CLICKTEST: window %dx%d" % (w, h))
        _state["points"] = [
            (w // 2, h // 2),               # main editor area
            (int(w * 0.85), int(h * 0.5)),  # right hand panel
            (w // 2, 40),                   # bottom bar
            (int(w * 0.5), h - 30),         # header
            (int(w * 0.1), int(h * 0.5)),   # left hand side
        ]

    if _state["index"] >= len(_state["points"]):
        print("CLICKTEST: finished without crashing")
        bpy.ops.wm.quit_blender()
        return None

    x, y = _state["points"][_state["index"]]
    _state["index"] += 1
    print("CLICKTEST: click %d at (%d, %d)" % (_state["index"], x, y))

    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    window.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
    window.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)
    return 0.5


bpy.app.timers.register(_tick, first_interval=1.5)
