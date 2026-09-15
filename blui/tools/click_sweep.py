# SPDX-License-Identifier: GPL-2.0-or-later
"""Sweep clicks across the whole BLUI window looking for a crash or an assert.

Requires --enable-event-simulate.

Run with:
    BLUI.exe --debug --enable-event-simulate --python tools/click_sweep.py

After every click an Escape is sent, so menus/popups opened by the click are
dismissed and the sweep cannot get stuck inside a popup.
"""

import bpy

_state = {"index": 0, "points": []}
STEP = 160


def _tick():
    window = bpy.context.window_manager.windows[0]

    if not _state["points"]:
        w, h = window.width, window.height
        points = []
        for y in range(30, h - 10, STEP):
            for x in range(20, w - 10, STEP):
                points.append((x, y))
        _state["points"] = points
        print("SWEEP: window %dx%d -> %d points" % (w, h, len(points)))

    if _state["index"] >= len(_state["points"]):
        print("SWEEP: finished %d clicks without crashing" % _state["index"])
        bpy.ops.wm.quit_blender()
        return None

    x, y = _state["points"][_state["index"]]
    _state["index"] += 1
    if _state["index"] % 20 == 0:
        print("SWEEP: click %d at (%d, %d)" % (_state["index"], x, y))

    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    window.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
    window.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)
    window.event_simulate(type="ESC", value="PRESS", x=x, y=y)
    window.event_simulate(type="ESC", value="RELEASE", x=x, y=y)
    return 0.06


bpy.app.timers.register(_tick, first_interval=1.5)
