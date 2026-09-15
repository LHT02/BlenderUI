# SPDX-License-Identifier: GPL-2.0-or-later
"""Check that Ctrl+S saves the focused component's own file.

BLUI has no document: the text editor writes its text file, the image editor
writes its image, and a viewer has nothing of its own to write. This drives
that end to end - it writes a text file, opens it in the text editor, changes
it, runs the Save operator, and reads the file back off disk to prove the write
happened to the real file rather than into some container.

Run with:
    BLUI.exe --factory-startup --python blui/tools/check_save_isolation.py -- <scratch-file>
"""

import os
import sys

import bpy

_scratch = None
_state = {"step": 0}
_original = "line one\nline two\n"
_edited = "line one\nline two\nline three - written by the editor\n"


def _parse_scratch():
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    if not argv:
        raise SystemExit("check_save_isolation.py: a scratch file path is required")
    return argv[0]


def _text_area(window):
    for area in window.screen.areas:
        if area.type == "TEXT_EDITOR":
            return area
    return None


def _override(window, area):
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    return bpy.context.temp_override(window=window, screen=window.screen,
                                     area=area, region=region)


def _step():
    window = bpy.context.window
    step = _state["step"]
    _state["step"] += 1

    if step == 0:
        with open(_scratch, "w", encoding="utf-8") as handle:
            handle.write(_original)
        print("SAVE: wrote scratch file %r" % _scratch)
        for workspace in bpy.data.workspaces:
            if workspace.name == "Text":
                window.workspace = workspace
                print("SAVE: switched to the Text workspace")
                break
        return 0.4

    area = _text_area(window)
    if area is None:
        print("SAVE: FAIL no TEXT_EDITOR area")
        bpy.ops.wm.quit_blender()
        return None

    if step == 1:
        with _override(window, area):
            result = bpy.ops.text.open(filepath=_scratch)
        print("SAVE: text.open -> %s" % (result,))
        return 0.3

    if step == 2:
        with _override(window, area):
            text = bpy.context.space_data.text
            print("SAVE: opened text=%r filepath=%r" % (text.name, text.filepath))
            text.clear()
            text.write(_edited)
            print("SAVE: buffer now has %d lines" % len(text.lines))
        return 0.3

    if step == 3:
        with _override(window, area):
            print("SAVE: operator poll = %s" % bpy.ops.wm.save_active_file.poll())
            result = bpy.ops.wm.save_active_file()
        print("SAVE: wm.save_active_file -> %s" % (result,))
        return 0.3

    with open(_scratch, "r", encoding="utf-8") as handle:
        on_disk = handle.read()
    print("SAVE: on disk now  %r" % on_disk)
    print("SAVE: RESULT %s" % ("PASS" if on_disk == _edited else "FAIL"))
    bpy.ops.wm.quit_blender()
    return None


def main():
    global _scratch
    _scratch = _parse_scratch()
    bpy.app.timers.register(_step, first_interval=0.8)


main()
