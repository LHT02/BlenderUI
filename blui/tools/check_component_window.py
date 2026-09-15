# SPDX-License-Identifier: GPL-2.0-or-later
"""Check that wm.window_new can open a named component in its own window.

BLUI has no workspace tab strip, so a component is opened as a window. This
verifies that the operator both creates the window and puts the requested
component in it, rather than copying whatever the source window showed.

Run with:
    BLUI.exe --factory-startup --python blui/tools/check_component_window.py
"""

import bpy

_state = {"step": 0}


def _windows():
    return bpy.context.window_manager.windows


def _summary():
    return [(w.workspace.name, [a.type for a in w.screen.areas]) for w in _windows()]


def _step():
    window = bpy.context.window
    step = _state["step"]
    _state["step"] += 1

    if step == 0:
        print("WIN: start %s" % (_summary(),))
        print("WIN: source workspace = %r" % window.workspace.name)
        with bpy.context.temp_override(window=window):
            result = bpy.ops.wm.window_new(workspace="Settings")
        print("WIN: wm.window_new(workspace='Settings') -> %s" % (result,))
        return 0.5

    if step == 1:
        summary = _summary()
        print("WIN: after %s" % (summary,))
        print("WIN: window count %d" % len(summary))
        opened = any(name == "Settings" for name, _areas in summary)
        print("WIN: RESULT_SETTINGS_WINDOW %s" % ("PASS" if opened else "FAIL"))
        return 0.2

    # A second one, copying the current component (no argument).
    if step == 2:
        with bpy.context.temp_override(window=window):
            result = bpy.ops.wm.window_new()
        print("WIN: wm.window_new() -> %s" % (result,))
        return 0.5

    if step == 3:
        print("WIN: final %s" % (_summary(),))
        print("WIN: DONE")
        bpy.ops.wm.quit_blender()
        return None

    return None


bpy.app.timers.register(_step, first_interval=2.5)
