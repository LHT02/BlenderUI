# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate BLUI's factory startup file.

BLUI ships a workspace set built around browsing files and viewing images, not
around modelling 3D scenes. This script rewrites the workspace list of the
loaded factory startup file and writes the result out as a new `startup.blend`,
which is then installed as `datafiles/startup.blend`.

Two constraints shape the implementation:

* It has to run with a real window - retyping an area and closing areas go
  through operators that need a window/screen/area context, which `--background`
  does not provide.
* `window.workspace = ...` does not update `window.screen` within the same
  script run; the switch is applied by the event loop. So the work is done one
  step per timer callback, which lets the window catch up between steps.

Run with:
    BLUI.exe --factory-startup --python tools/build_blui_startup.py -- \
        --output <path to startup.blend>
"""

import sys

import bpy

# (workspace name, space type for its single area)
BLUI_WORKSPACES = (
    ("Files", "FILE_BROWSER"),
    ("Images", "IMAGE_EDITOR"),
    ("Text", "TEXT_EDITOR"),
    ("Video", "SEQUENCE_EDITOR"),
    ("Settings", "PREFERENCES"),
    ("Console", "CONSOLE"),
)

_plan = []
_output = None


def _parse_output():
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    if "--output" not in argv:
        raise SystemExit("build_blui_startup.py: --output <path> is required")
    return argv[argv.index("--output") + 1]


def _build_plan():
    all_ws = list(bpy.data.workspaces)
    keep = all_ws[: len(BLUI_WORKSPACES)]
    drop = all_ws[len(BLUI_WORKSPACES) :]

    plan = []
    for workspace, (name, space) in zip(keep, BLUI_WORKSPACES):
        plan.append(("activate", workspace))
        screens = workspace.screens
        n_areas = len(screens[0].areas) if screens else 0
        for _ in range(max(0, n_areas - 1)):
            plan.append(("close", None))
        plan.append(("retype", space))
        plan.append(("rename", name))
    for workspace in drop:
        plan.append(("activate", workspace))
        plan.append(("delete", None))
    plan.append(("select", "Files"))
    plan.append(("save", None))
    return plan


def _step():
    global _plan

    if not _plan:
        print("STARTUP: plan exhausted without saving")
        bpy.ops.wm.quit_blender()
        return None

    action, payload = _plan.pop(0)
    window = bpy.context.window

    try:
        if action == "activate":
            window.workspace = payload
            print("STARTUP: activate %r" % payload.name)
        elif action == "close":
            screen = window.screen
            if len(screen.areas) > 1:
                victim = sorted(screen.areas, key=lambda a: a.width * a.height)[0]
                with bpy.context.temp_override(window=window, screen=screen, area=victim):
                    result = bpy.ops.screen.area_close()
                print("STARTUP:   close %s -> %s" % (victim.type, result))
            else:
                print("STARTUP:   close skipped (single area)")
        elif action == "retype":
            screen = window.screen
            main = max(screen.areas, key=lambda a: a.width * a.height)
            if main.type != payload:
                with bpy.context.temp_override(window=window, screen=screen, area=main):
                    result = bpy.ops.screen.space_type_set_or_cycle(space_type=payload)
                print("STARTUP:   retype %s -> %s (%s)" % (main.type, payload, result))
            else:
                print("STARTUP:   retype not needed (%s)" % payload)
        elif action == "rename":
            window.workspace.name = payload
            if window.screen:
                window.screen.name = payload
            print("STARTUP:   rename -> %r" % payload)
        elif action == "delete":
            name = window.workspace.name
            result = bpy.ops.workspace.delete()
            print("STARTUP: delete %r -> %s" % (name, result))
        elif action == "select":
            for workspace in bpy.data.workspaces:
                if workspace.name == payload:
                    window.workspace = workspace
                    print("STARTUP: selected %r" % payload)
                    break
        elif action == "save":
            summary = [(w.name, [s.type for sc in w.screens for a in sc.areas for s in a.spaces])
                       for w in bpy.data.workspaces]
            print("STARTUP: final workspaces: %s" % summary)
            bpy.ops.wm.save_as_mainfile(filepath=_output, check_existing=False, compress=False)
            print("STARTUP: wrote %s" % _output)
            bpy.ops.wm.quit_blender()
            return None
    except Exception as exc:  # noqa: BLE001
        print("STARTUP: ERROR on %s: %s" % (action, exc))

    return 0.05


def main():
    global _plan, _output
    if bpy.context.window is None:
        raise SystemExit("build_blui_startup.py: needs a window (do not use --background)")
    _output = _parse_output()
    print("STARTUP: existing workspaces: %s" % [w.name for w in bpy.data.workspaces])
    _plan = _build_plan()
    print("STARTUP: plan has %d steps" % len(_plan))
    bpy.app.timers.register(_step, first_interval=0.4)


main()
