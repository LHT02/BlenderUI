# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure whether two component windows share their editor state.

Blender gives each window a workspace hook, and the hook points at a layout
which owns a screen. If two windows end up on the same layout they share the
same screen, which means they share the same SpaceText / SpaceImage - so two
text editor windows would be two views of one document rather than two
independent editors. That is the isolation this checks for.

It also measures the layer underneath, which is a separate question: the
datablocks live in one `Main`, so `bpy.data.texts` and `bpy.data.images` are
common to every window even when no two windows are looking at the same one.
That is the open-document list, and it is not yet isolated. The measurement is
reported either way; pass `--strict` to make it fail instead, which is the test
to run once the document layer is split per window.

Run with:
    BLUI.exe --factory-startup --python blui/tools/check_window_isolation.py
    BLUI.exe --factory-startup --python blui/tools/check_window_isolation.py -- --strict
"""

import os
import sys

import bpy

_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
_STRICT = "--strict" in _argv

_state = {"step": 0, "failures": [], "documents_shared": None}


def _report(ok, message):
    print("ISO:   %s %s" % ("PASS" if ok else "FAIL", message))
    if not ok:
        _state["failures"].append(message)


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

        # Does opening a text file in one window leak into the other?
        text_windows = [w for w in windows if w.screen.areas[0].type == "TEXT_EDITOR"]
        if len(text_windows) >= 2:
            a = text_windows[0].screen.areas[0].spaces.active
            b = text_windows[1].screen.areas[0].spaces.active
            print("ISO: text space a=%s b=%s same_object=%s"
                  % (a.as_pointer(), b.as_pointer(), a.as_pointer() == b.as_pointer()))

        _report(not same, "each window has its own screen")

        if len(text_windows) >= 2:
            return _measure_documents(text_windows[0], text_windows[1])

        _finish()
        return None

    return None


def _measure_documents(window_a, window_b):
    """Open one document per window and see whose list they land in."""
    space_a = window_a.screen.areas[0].spaces.active
    space_b = window_b.screen.areas[0].spaces.active

    text_a = bpy.data.texts.new("blui_iso_a")
    text_b = bpy.data.texts.new("blui_iso_b")
    space_a.text = text_a
    space_b.text = text_b

    # The editors are the windows' own - this part is done.
    _report(space_a.text is text_a, "window A is editing its own document")
    _report(space_b.text is text_b, "window B is editing its own document")
    _report(space_a.text is not space_b.text, "the two windows are not on one document")

    # The documents are not. Both landed in the same `Main`, so either window
    # can see the other's open file.
    names = sorted(t.name for t in bpy.data.texts)
    visible_to_a = [t.name for t in bpy.data.texts]
    shared = "blui_iso_b" in visible_to_a and "blui_iso_a" in visible_to_a
    _state["documents_shared"] = shared
    print("ISO: bpy.data.texts = %s" % names)
    print("ISO: window A can see %d open text(s), including window B's: %s"
          % (len(visible_to_a), shared))

    if _STRICT:
        _report(not shared, "a window's open-document list holds only its own documents")
    else:
        print("ISO:   NOTE open-document list is shared (not isolated) - "
              "see Stage 6 in the README; run with --strict to assert the opposite")

    bpy.data.texts.remove(text_a, do_unlink=True)
    bpy.data.texts.remove(text_b, do_unlink=True)
    _finish()
    return None


def _finish():
    failures = _state["failures"]
    shared = _state["documents_shared"]
    print("ISO: RESULT %s" % ("EDITORS-ISOLATED" if not failures else "SHARED-STATE"))
    if shared is None:
        print("ISO: DOCUMENTS unknown (no two text windows to compare)")
    else:
        print("ISO: DOCUMENTS %s" % ("SHARED (not isolated)" if shared else "ISOLATED"))
    print("ISO: RESULT_%s" % ("PASS" if not failures else "FAIL"))
    # `wm.quit_blender()` would always leave exit status 0, and a check that
    # cannot fail loudly is not a check.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1 if failures else 0)


bpy.app.timers.register(_step, first_interval=2.5)
