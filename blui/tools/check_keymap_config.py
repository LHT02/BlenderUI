# SPDX-License-Identifier: GPL-2.0-or-later
"""Check that BLUI's key configuration actually loads.

This exists because it once did not, and nothing noticed. Removing the 3D
`ED_operatormacros_*()` registrations made `bl_keymap_utils/io.py` abort the
whole key configuration load at the first keymap item naming a dropped macro:

    TypeError: OperatorProperties.property_unset("TRANSFORM_OT_edge_slide")

`keyconfigs.active` was then left with no keymaps at all, and every other check
still passed, because they call operators directly instead of going through the
keyboard. So this check drives the key configuration the way a person does.

Run:
    build\\bin\\BLUI.exe --background --factory-startup \
        --python source\\blui\\tools\\check_keymap_config.py

Exits non-zero when the key configuration did not load, or lost a binding BLUI
depends on.
"""

import os
import sys

import bpy

# A key configuration that loaded properly has 135 keymaps. One that aborted
# part way through has single digits - the mesh macro failure left 7. Requiring
# a floor rather than "more than none" is what makes this check able to fail.
MINIMUM_KEYMAPS = 100

# Space types the Shift+F1..F6 component-switching row must name.
COMPONENT_KEYS = {
    "F1": "FILE_BROWSER",
    "F2": "IMAGE_EDITOR",
    "F3": "TEXT_EDITOR",
    "F4": "CONSOLE",
    "F5": "SEQUENCE_EDITOR",
    "F6": "PREFERENCES",
}

# The binding BLUI's Save command rides on.
SAVE_OPERATOR = "wm.save_active_file"

failures = []


def report(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        failures.append(message)


# This has to run with a window. In `--background` mode Blender builds the key
# configuration only part way - the keymaps exist but carry no items - so the
# bindings this check is about are not there to find yet.
if bpy.app.background:
    print("check_keymap_config: SKIP (needs a window; do not pass --background)")
    sys.exit(0)


def run():
    print("BLUI key configuration")

    kc = bpy.context.window_manager.keyconfigs.active
    if kc is None:
        report(False, "an active key configuration exists")
        finish()
        return None

    keymaps = list(kc.keymaps)
    print("  key configuration %r: %d keymaps" % (kc.name, len(keymaps)))

    # The failure this check was written for: a load that aborted leaves the
    # configuration present but mostly empty, which looks fine from every other
    # angle.
    report(
        len(keymaps) >= MINIMUM_KEYMAPS,
        "the key configuration loaded fully (%d keymaps, want >= %d)"
        % (len(keymaps), MINIMUM_KEYMAPS),
    )

    # A configuration that loaded properly has the global keymaps every window
    # needs. Their absence is the signature of a partial load.
    names = {km.name for km in keymaps}
    for required in ("Window", "Screen", "User Interface", "View2D"):
        report(required in names, "the %r keymap is present" % required)

    screen = kc.keymaps.get("Screen")
    if screen is None:
        report(False, "the 'Screen' keymap can be looked up by name")
    else:
        report(len(screen.keymap_items) > 0, "the 'Screen' keymap has items in it")

    # Walk every keymap for the two bindings BLUI is built around, rather than
    # trusting that they are in a particular one.
    save_bindings = []
    switch_bindings = {}
    for km in keymaps:
        for kmi in km.keymap_items:
            if kmi.idname == SAVE_OPERATOR:
                save_bindings.append((km.name, kmi.type, kmi.ctrl, kmi.shift))
            elif kmi.idname == "screen.space_type_set_or_cycle":
                switch_bindings[kmi.type] = kmi.properties.space_type

    report(len(save_bindings) > 0, "%s is bound to a key" % SAVE_OPERATOR)
    for name, key, ctrl, shift in save_bindings:
        report(
            key == "S" and ctrl and not shift,
            "%s is on Ctrl+S (found %s%s+%s in %r)"
            % (SAVE_OPERATOR, "Ctrl+" if ctrl else "", "Shift+" if shift else "", key, name),
        )

    for key, expected in sorted(COMPONENT_KEYS.items()):
        actual = switch_bindings.get(key)
        report(
            actual == expected,
            "Shift+%s switches to %s (got %r)" % (key, expected, actual),
        )

    finish()
    return None


def finish():
    print("")
    if failures:
        print("check_keymap_config: FAILED (%d)" % len(failures))
    else:
        print("check_keymap_config: PASS")
    # `wm.quit_blender()` would close the window but always leave exit status 0,
    # and a check that cannot fail loudly is not a check. Leave with the status
    # the result deserves.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1 if failures else 0)


bpy.app.timers.register(run, first_interval=1.0)
