# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure whether two component windows share their editor state.

Blender gives each window a workspace hook, and the hook points at a layout
which owns a screen. If two windows end up on the same layout they share the
same screen, which means they share the same SpaceText / SpaceImage - so two
text editor windows would be two views of one document rather than two
independent editors. That is the isolation this checks for.

Run with:
    BLUI.exe --factory-startup --python blui/tools/check_window_isolation.py
"""

import bpy

_state = {"step": 0}


def _describe(window):
    lines = []
    for area in window.screen.areas:
        space = area.spaces.active
        detail = ""
        if area.type == "TEXT_EDITOR":
            text = getattr(space, "text", None)
            detail = "text=%r" % (text.name if text else None)
        elif area.type == "IMAGE_EDITOR":
            image = getattr(space, "image", None)
            detail = "image=%r" % (image.name if image else None)
        lines.append("%s(%s)" % (area.type, detail))
    return "workspace=%r screen=%r areas=%s" % (
        window.workspace.name,
        window.screen.name,
        lines,
    )


def _step():
    window = bpy.context.window
    step = _state["step"]
    _state["step"] += 1

    if step == 0:
        print("ISO: window0 %s" % _describe(window))
        with bpy.context.temp_override(window=window):
            bpy.ops.wm.window_new(workspace="Text")
        return 0.5

    if step == 1:
        print("ISO: window1 %s" % _describe(bpy.context.window_manager.windows[1]))
        with bpy.context.temp_override(window=window):
            bpy.ops.wm.window_new(workspace="Text")
        return 0.5

    if step == 2:
        windows = list(bpy.context.window_manager.windows)
        print("ISO: %d windows" % len(windows))
        screens = []
        for index, win in enumerate(windows):
            print("ISO:   [%d] %s" % (index, _describe(win)))
            screens.append(win.screen.as_pointer())

        same = len(set(screens)) != len(screens)
        print("ISO: distinct screens = %d of %d" % (len(set(screens)), len(screens)))
        print("ISO: RESULT %s" % ("SHARED-STATE (not isolated)" if same else "ISOLATED"))

        # Does opening a text file in one window leak into the other?
        text_windows = [w for w in windows if w.screen.areas[0].type == "TEXT_EDITOR"]
        if len(text_windows) >= 2:
            a = text_windows[0].screen.areas[0].spaces.active
            b = text_windows[1].screen.areas[0].spaces.active
            print("ISO: text space a=%s b=%s same_object=%s"
                  % (a.as_pointer(), b.as_pointer(), a.as_pointer() == b.as_pointer()))
        bpy.ops.wm.quit_blender()
        return None

    return None


bpy.app.timers.register(_step, first_interval=2.5)
