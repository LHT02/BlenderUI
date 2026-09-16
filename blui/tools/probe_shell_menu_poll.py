# SPDX-License-Identifier: GPL-2.0-or-later
"""Can the shell menu entry even be pressed?

A menu entry whose operator fails its poll is drawn greyed out and does
nothing when clicked, which is indistinguishable from a broken implementation.
This reports the poll result for `file.shell_context_menu` from inside the file
browser, where the context is real.

    BLUI.exe --factory-startup --python blui/tools/probe_shell_menu_poll.py
"""

import sys

import bpy


def _run():
    print("POLL: file.shell_context_menu registered: %s"
          % hasattr(bpy.ops.file, "shell_context_menu"))

    # A poll is only meaningful with the context the operator would really get.
    # Compare against operators that are known to work in this browser: if those
    # are also False, the probe's context is wrong rather than the operator's.
    wm = bpy.context.window_manager
    window = wm.windows[0] if wm.windows else None
    area = None
    region = None
    if window is not None:
        for a in window.screen.areas:
            if a.type == "FILE_BROWSER":
                area = a
                for r in a.regions:
                    if r.type == "WINDOW":
                        region = r
                break

    def poll(name, **extra):
        op = getattr(bpy.ops.file, name)
        try:
            with bpy.context.temp_override(area=area, region=region, **extra):
                return op.poll()
        except Exception as exc:  # noqa: BLE001
            return "error: %s" % exc

    print("POLL: area=%r region=%r" % (area is not None, region is not None))
    print("POLL: file.rename.poll()   -> %r" % poll("rename"))
    print("POLL: file.delete.poll()   -> %r" % poll("delete"))
    print("POLL: file.select_all.poll() -> %r" % poll("select_all"))
    print("POLL: file.clipboard_copy.poll() -> %r" % poll("clipboard_copy"))
    print("POLL: file.external_operation.poll() -> %r" % poll("external_operation"))
    result = poll("shell_context_menu")
    print("POLL: file.shell_context_menu.poll() -> %r" % result)

    if area is not None:
        print("POLL: directory=%r" % area.spaces.active.params.directory)

    print("POLL: RESULT %s" % ("PRESSABLE" if result is True else "GREYED-OUT"))
    sys.stdout.flush()
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=2.0)
