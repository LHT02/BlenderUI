# SPDX-License-Identifier: GPL-2.0-or-later
"""Which file-browser operations are actually available?

A poll that fails does not break anything loudly: the menu entry is drawn
greyed out and the keyboard shortcut does nothing, which looks exactly like a
feature that was never wired up. One of these was spotted by accident -
`file.delete` reported False while its neighbours reported True - so this walks
the whole `file.*` namespace and reports each poll with the file browser's own
area and region in context.

    BLUI.exe --factory-startup --python blui/tools/probe_file_ops.py
"""

import sys

import bpy

# Operations a file manager is expected to offer, so a failure here is a
# missing feature rather than an irrelevant operator. `filenum` is deliberately
# absent: its poll requires FILE_CHECK_EXISTING, which is save-dialog mode, so
# being unavailable while browsing is correct rather than a gap.
EXPECTED = [
    "select", "select_all", "select_box",
    "rename", "delete", "directory_new",
    "clipboard_copy", "clipboard_cut", "clipboard_paste",
    "previous", "next", "parent", "refresh",
    "bookmark_add", "bookmark_toggle", "bookmark_delete",
    "smoothscroll", "start_filter", "edit_directory_path",
    "external_operation", "shell_context_menu",
]


def _report(area, region, window, tag):
    names = [n for n in dir(bpy.ops.file) if not n.startswith("_")]
    unavailable = []
    lines = []
    for name in sorted(names):
        op = getattr(bpy.ops.file, name)
        try:
            with bpy.context.temp_override(area=area, region=region, window=window):
                ok = op.poll()
        except Exception as exc:  # noqa: BLE001
            ok = "error: %s" % exc
        lines.append("FILEOPS:   %s %-28s %r" % ("ok  " if ok is True else "NO  ", name, ok))
        if ok is not True and name in EXPECTED:
            unavailable.append(name)

    print("FILEOPS: --- %s ---" % tag)
    for line in lines:
        print(line)
    print("FILEOPS: %s unavailable: %s" % (tag, ", ".join(unavailable) or "(none)"))
    return unavailable


def _run():
    wm = bpy.context.window_manager
    window = wm.windows[0] if wm.windows else None
    area = region = None
    if window is not None:
        for a in window.screen.areas:
            if a.type == "FILE_BROWSER":
                area = a
                for r in a.regions:
                    if r.type == "WINDOW":
                        region = r
                break

    print("FILEOPS: window=%r area=%r region=%r" % (window is not None, area is not None, region is not None))
    if area is None:
        print("FILEOPS: RESULT NO-FILE-BROWSER")
        sys.stdout.flush()
        bpy.ops.wm.quit_blender()
        return None

    # Nothing selected first. Several polls require a selection, so a failure
    # here is the correct answer rather than a missing feature - which is worth
    # seeing, because it is what made `file.delete` look broken.
    _report(area, region, window, "with nothing selected")

    x = region.x + region.width // 3
    y = region.y + region.height - 80
    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    window.event_simulate(type="RIGHTMOUSE", value="PRESS", x=x, y=y)
    window.event_simulate(type="RIGHTMOUSE", value="RELEASE", x=x, y=y)
    window.event_simulate(type="ESC", value="PRESS", x=x, y=y)
    window.event_simulate(type="ESC", value="RELEASE", x=x, y=y)
    return 0.8


def _step2():
    window = bpy.context.window_manager.windows[0]
    area = region = None
    for a in window.screen.areas:
        if a.type == "FILE_BROWSER":
            area = a
            for r in a.regions:
                if r.type == "WINDOW":
                    region = r
            break

    unavailable = _report(area, region, window, "with a file selected")
    print("FILEOPS: RESULT %s" % ("ALL-EXPECTED-OK" if not unavailable else "MISSING-OPERATIONS"))
    sys.stdout.flush()
    bpy.ops.wm.quit_blender()
    return None


def _wrapper():
    try:
        result = _run()
        if result is not None:
            bpy.app.timers.register(_step2, first_interval=result)
        return None
    except Exception as exc:  # noqa: BLE001
        print("FILEOPS: EXCEPTION %r" % (exc,))
        sys.stdout.flush()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(_wrapper, first_interval=2.5)
