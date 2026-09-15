# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise right-click, double-click and drag, which a plain click sweep misses.

Requires --enable-event-simulate.

Run with:
    BLUI.exe --enable-event-simulate --python tools/interaction_test.py
"""

import bpy

_state = {"step": 0, "x": 0, "y": 0}
_STEPS = 14


def _tick():
    window = bpy.context.window_manager.windows[0]
    if _state["step"] == 0:
        w, h = window.width, window.height
        _state["x"], _state["y"] = w // 2, h // 2
        print("INTERACT: window %dx%d centre (%d,%d)" % (w, h, _state["x"], _state["y"]))

    step = _state["step"]
    _state["step"] += 1
    x, y = _state["x"], _state["y"]
    print("INTERACT: step %d" % step)

    if step == 0:  # right click -> context menu
        window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
        window.event_simulate(type="RIGHTMOUSE", value="PRESS", x=x, y=y)
        window.event_simulate(type="RIGHTMOUSE", value="RELEASE", x=x, y=y)
    elif step == 1:
        window.event_simulate(type="ESC", value="PRESS", x=x, y=y)
        window.event_simulate(type="ESC", value="RELEASE", x=x, y=y)
    elif step == 2:  # double click
        for _ in range(2):
            window.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
            window.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)
    elif step == 3:
        window.event_simulate(type="ESC", value="PRESS", x=x, y=y)
        window.event_simulate(type="ESC", value="RELEASE", x=x, y=y)
    elif step == 4:  # drag: press, move, release
        window.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
    elif 5 <= step <= 10:
        nx = x + (step - 4) * 30
        ny = y + (step - 4) * 20
        window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=nx, y=ny)
        _state["x"], _state["y"] = nx, ny
    elif step == 11:
        window.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)
    elif step == 12:
        window.event_simulate(type="ESC", value="PRESS", x=x, y=y)
        window.event_simulate(type="ESC", value="RELEASE", x=x, y=y)
    else:
        print("INTERACT: finished without crashing")
        bpy.ops.wm.quit_blender()
        return None

    return 0.3


bpy.timer = bpy.app.timers.register(_tick, first_interval=1.5)
print("INTERACT: armed")
