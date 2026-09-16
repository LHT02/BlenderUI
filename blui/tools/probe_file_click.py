# SPDX-License-Identifier: GPL-2.0-or-later
"""What does a right-click in the file list actually leave behind?

The shell menu entry, the "External" submenu and Ctrl+C all depend on the same
thing: that right-clicking a file makes it the *active* file, so a menu entry
invoked later (which cannot see where the cursor was) knows what was clicked.
That chain has never been measured - the checks only ever looked at whether the
bindings and operators exist, which they do.

This simulates a right-press over the file list and reports what the browser
remembers afterwards. Run with:

    BLUI.exe --factory-startup --enable-event-simulate \
        --python blui/tools/probe_file_click.py
"""

import sys

import bpy

_state = {"step": 0, "before": None}


def _file_area(window):
    for area in window.screen.areas:
        if area.type == "FILE_BROWSER":
            return area
    return None


def _window_region(area):
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    return None


def _report(window, tag):
    area = _file_area(window)
    if area is None:
        print("CLICK: no FILE_BROWSER area")
        return None
    params = area.spaces.active.params
    print("CLICK: %s directory=%r" % (tag, params.directory))
    return None


def _step():
    step = _state["step"]
    _state["step"] += 1
    window = bpy.context.window_manager.windows[0]

    if step == 0:
        area = _file_area(window)
        if area is None:
            print("CLICK: RESULT NO-FILE-AREA")
            bpy.ops.wm.quit_blender()
            return None
        region = _window_region(area)
        print("CLICK: area=(%d,%d %dx%d) window_region=(%d,%d %dx%d)"
              % (area.x, area.y, area.width, area.height,
                 region.x, region.y, region.width, region.height))
        _state["before"] = _report(window, "before")
        # A few rows down from the top of the list, where file entries live
        # rather than the breadcrumb/toolbar strip.
        _state["x"] = region.x + region.width // 2
        _state["y"] = region.y + region.height - 60
        window.event_simulate(type="MOUSEMOVE", value="NOTHING",
                              x=_state["x"], y=_state["y"])
        return 0.4

    if step == 1:
        window.event_simulate(type="RIGHTMOUSE", value="PRESS",
                              x=_state["x"], y=_state["y"])
        window.event_simulate(type="RIGHTMOUSE", value="RELEASE",
                              x=_state["x"], y=_state["y"])
        return 0.5

    if step == 2:
        _state["after"] = _report(window, "after right-click")
        window.event_simulate(type="ESC", value="PRESS", x=_state["x"], y=_state["y"])
        window.event_simulate(type="ESC", value="RELEASE", x=_state["x"], y=_state["y"])
        return 0.4

    if step == 3:
        print("CLICK: RESULT simulated right-click sent - see the BLUI file.select log line")
        sys.stdout.flush()
        bpy.ops.wm.quit_blender()
        return None

    return None


def _step_wrapper():
    try:
        return _step()
    except Exception as exc:  # noqa: BLE001
        print("CLICK: EXCEPTION %s" % exc)
        sys.stdout.flush()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(_step_wrapper, first_interval=2.0)
