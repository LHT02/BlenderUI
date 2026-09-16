# SPDX-License-Identifier: GPL-2.0-or-later
"""Check that BLUI's key configurations actually load, and that nothing in them
points at an operator that no longer exists.

This exists because it once did not, and nothing noticed. Removing the 3D
`ED_operatormacros_*()` registrations made `bl_keymap_utils/io.py` abort the
whole key configuration load at the first keymap item naming a dropped macro:

    TypeError: OperatorProperties.property_unset("TRANSFORM_OT_edge_slide")

`keyconfigs.active` was then left with no keymaps at all, and every other check
still passed, because they call operators directly instead of going through the
keyboard. So this check drives the key configuration the way a person does.

Two blind spots were found in this script by review, and both are now closed.
They are written down here because they are the kind of thing that silently
comes back:

1. **Only the active configuration was checked.** The original version read
   `keyconfigs.active` and stopped, so the presets BLUI ships that are not the
   active one were never looked at. This is not hypothetical: the annotation
   deletion removed `builtin.annotate` from `blender_default.py` but left two
   references in `industry_compatible_data.py` (in `_template_items_basic_tools`,
   which Object Mode and Grease Pencil Stroke Edit Mode share, and in the Image
   keymap), producing three dangling `wm.tool_set_by_id` bindings. Every check
   passed. It happened to be inert rather than an abort - activating the preset
   still returned `{'FINISHED'}` - but that was luck. All presets are now
   checked.

   Doing that turned up a second correction: **a preset being shipped is not the
   same as it being instantiated.** Only `Blender.py` is loaded at startup;
   `Blender_27x` and `Industry_Compatible` are created on demand when someone
   picks them in Preferences > Input, so at startup `keyconfigs` holds just
   `Blender`, `Blender addon` and `Blender user`. Touching `kc.preferences` does
   not materialize them. The check therefore tests the preset *file* exists and
   activates it *by filepath* - the path the UI uses - rather than looking for
   it in `keyconfigs`.

2. **Only "is what should be there present" was asserted.** Nothing looked at
   whether the things a keymap *names* still exist. A keymap item whose
   `idname` refers to an unregistered operator is exactly what a module deletion
   produces, and it is invisible to a "count the keymaps" check. The
   dangling-binding scan below is the other half.

   Run for the first time on 2026-09-16, it found **34 dangling bindings** -
   `Blender` 16, `Blender_27x` 13, `Industry_Compatible` 5 - none of them the
   annotation residue above. See "Verification suite coverage boundaries" in
   `blui/README.md` for the breakdown and the root cause of each group. They are
   **not yet cleaned up**, so this check currently exits 1 on purpose.

Run::
    build\\bin\\BLUI.exe --factory-startup \\
        --python source\\blui\\tools\\check_keymap_config.py

The invocation matters: without `--factory-startup` the run picks up whatever
user configuration is on disk, and the counts below will not match.

Exits non-zero when a key configuration did not load, lost a binding BLUI
depends on, or names an operator that is not registered.
"""

import os
import sys

import bpy

# A key configuration that loaded properly has ~100 keymaps. One that aborted
# part way through has single digits - the mesh macro failure left 7. Requiring
# a floor rather than "more than none" is what makes this check able to fail.
#
# The earlier value here was 135, which was Blender's unmodified count and never
# BLUI's. Measured 2026-09-16 under `--factory-startup`: Blender 112,
# Blender_27x 103, Industry_Compatible 103. A threshold above the real count
# makes the check unable to pass, which reads as a permanent failure and gets
# ignored - so the floor sits below all three and the exact counts are asserted
# separately in MEASURED_KEYMAP_COUNTS.
MINIMUM_KEYMAPS = 100

# Exact counts, so "one preset silently lost 40 keymaps but is still above the
# floor" is caught. Keep in step with MEASURED_DANGLING_BINDINGS below.
MEASURED_KEYMAP_COUNTS = {
    "Blender": 112,
    "Blender_27x": 103,
    "Industry_Compatible": 103,
}

# The presets BLUI ships, from `scripts/presets/keyconfig/`. Named explicitly
# rather than discovered, so a preset disappearing from the install is itself a
# finding rather than something the check silently stops covering.
EXPECTED_PRESETS = ["Blender", "Blender_27x", "Industry_Compatible"]

# Keymap items that are allowed to name an operator which is not registered.
# Every entry here is a deliberate exception and should say why.
#
# Deliberately EMPTY, and the check therefore FAILS today with 34 findings.
# That is the honest state, not an oversight.
#
# The tempting move is to park the `view3d.*` group here - BLUI has no 3D
# viewport, so those bindings are unreachable by construction and "harmless".
# It is the wrong move for two reasons:
#
#   * It would also silence the `object.duplicate_move` and `collection.*`
#     bindings, which live in Object Mode and *are* reachable in workspaces
#     BLUI ships. Those are real bugs, not unreachable residue.
#   * An allowlist that gets populated to make a suite green is how the suite
#     stops being able to fail - which is the exact failure this whole exercise
#     is about.
#
# The correct fix is to delete the keymap items that name the unregistered
# operators, not to excuse them. Until that happens, a red run here is the
# signal working. If an exception is ever genuinely warranted, it goes in this
# dict with the reason written next to it.
DANGLING_ALLOWED = {}

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

# What the dangling-binding scan finds, measured 2026-09-16 with the
# `--factory-startup` invocation above. Recorded because a check that can only
# ever print 0 is indistinguishable from a check that is not running, and
# because these are the numbers a future round has to drive to zero. See the
# coverage-boundaries section of `blui/README.md` for the root cause of each.
MEASURED_DANGLING_BINDINGS = {
    "Blender": 16,
    "Blender_27x": 13,
    "Industry_Compatible": 5,
}

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


def preset_paths():
    """Map preset name -> the `.py` file `preferences.keyconfig_activate` wants.

    The operator's property is `filepath` (a path to the preset script), not a
    bare name - passing `file=` raises `TypeError: keyword "file" unrecognized`
    *inside the timer*, which then leaves the process to die of an access
    violation rather than with a readable failure. Resolving the name to a real
    path here keeps that mistake from being repeated.
    """
    from os.path import join
    directory = bpy.utils.resource_path("LOCAL")
    directory = join(directory, "scripts", "presets", "keyconfig")
    found = {}
    try:
        import os
        names = os.listdir(directory)
    except OSError:
        return found
    for entry in names:
        if entry.endswith(".py"):
            found[entry[:-3]] = join(directory, entry)
    return found


def operator_exists(idname):
    """Does `category.operator` resolve to a registered operator?

    `idname` is what a keymap item stores, e.g. `object.gpencil_add`. Looking it
    up on `bpy.ops` is the only way to ask the running binary - reading the
    keymap data files cannot tell you, because the operator may be registered
    from C.
    """
    if "." not in idname:
        # Not an operator reference at all (some items carry a bare name for a
        # menu or a timer). Not this check's business.
        return True
    category, name = idname.split(".", 1)
    if name in ("", "*"):
        return True
    group = getattr(bpy.ops, category, None)
    if group is None:
        return False
    op = getattr(group, name, None)
    if op is None:
        return False
    try:
        op.get_rna_type()
    except Exception:
        return False
    return True


def scan_dangling(kc):
    """Every `idname` in `kc` that does not resolve. Returns a sorted list."""
    dangling = []
    for km in kc.keymaps:
        for kmi in km.keymap_items:
            idname = kmi.idname
            if not idname or idname in DANGLING_ALLOWED:
                continue
            if not operator_exists(idname):
                dangling.append((km.name, idname))
    return dangling


def activate(path):
    """Activate the preset script at `path`. Returns (ok, detail).

    Wrapped rather than trusted, because a preset whose script *raises* takes
    the whole run down with it. `bpy.utils.keyconfig_set()` calls
    `execfile(filepath)` inside a bare `try/except` that only stores the
    traceback for the `report` callback - and the operator passes no callback,
    so the exception propagates straight out through the operator call. This
    was measured: `keyconfig_activate(filepath="Industry_Compatible")` raised

        AttributeError: 'NoneType' object has no attribute 'loader'

    from `bpy/utils/__init__.py` line 93. A check that dies instead of
    reporting cannot report anything, so the exception is caught here and
    turned into an ordinary failure.
    """
    try:
        result = bpy.ops.preferences.keyconfig_activate(filepath=path)
    except Exception as exc:  # noqa: BLE001 - a preset that raises is a finding
        return False, "%s: %s" % (type(exc).__name__, exc)
    if "FINISHED" not in result:
        return False, "operator returned %s" % (result,)
    return True, None


def check_preset(name, path):
    """Activate `name` and run the per-configuration checks. Returns (ok, count)."""
    ok, detail = activate(path)
    if not ok:
        report(False, "preset %r activates (%s)" % (name, detail))
        return False, None

    kc = bpy.context.window_manager.keyconfigs.active
    if kc is None:
        report(False, "preset %r leaves an active key configuration" % name)
        return False, None
    if kc.name != name:
        # Activating by file name is how Blender maps a preset to a config; a
        # mismatch means the mapping is off, not that the check failed.
        print("  note: activated %r reports as %r" % (name, kc.name))

    keymaps = list(kc.keymaps)
    report(
        len(keymaps) >= MINIMUM_KEYMAPS,
        "preset %r loaded fully (%d keymaps, want >= %d)"
        % (name, len(keymaps), MINIMUM_KEYMAPS),
    )
    expected_keymaps = MEASURED_KEYMAP_COUNTS.get(name)
    if expected_keymaps is not None:
        report(
            len(keymaps) == expected_keymaps,
            "preset %r has its measured keymap count (%d, was %d on 2026-09-16)"
            % (name, len(keymaps), expected_keymaps),
        )

    dangling = scan_dangling(kc)
    expected = MEASURED_DANGLING_BINDINGS.get(name)
    report(
        not dangling,
        "preset %r has no dangling operator bindings (%d found)" % (name, len(dangling)),
    )
    if expected is not None:
        # Reported separately from the pass/fail above so the number is on the
        # record either way. It is currently expected to be non-zero; what this
        # guards is it getting *worse*. Without it, a round that fixed 30 of 34
        # and a round that broke 30 more would read identically.
        report(
            len(dangling) <= expected,
            "preset %r has not gained dangling bindings (%d, was %d on 2026-09-16)"
            % (name, len(dangling), expected),
        )
    for keymap_name, idname in dangling[:20]:
        print("        %s -> %s" % (keymap_name, idname))
    if len(dangling) > 20:
        print("        ... and %d more" % (len(dangling) - 20))

    # The count alone cannot tell "known, unfixed" from "just regressed". Say
    # which one this is, so a round that makes it worse is not read as progress.
    known = MEASURED_DANGLING_BINDINGS.get(name)
    if known is not None and len(dangling) != known:
        if len(dangling) > known:
            print("  note: %r regressed - %d dangling, was %d"
                  % (name, len(dangling), known))
        else:
            print("  note: %r improved - %d dangling, was %d"
                  % (name, len(dangling), known))

    return True, len(keymaps)


def run():
    print("BLUI key configuration")

    paths = preset_paths()
    print("  preset files found: %s"
          % ", ".join("%s=%s" % (k, paths[k]) for k in sorted(paths)))

    # A preset is shipped if it is on disk - NOT if it is already instantiated.
    # Only `Blender.py` is loaded at startup; `Blender_27x` and
    # `Industry_Compatible` are created on demand the first time someone picks
    # them in Preferences > Input. Measuring "is it in `keyconfigs`" therefore
    # says nothing about whether BLUI ships it, and would report the two
    # on-demand presets as missing forever. The file existing is the real test;
    # activating it by path below is what actually exercises it.
    for name in EXPECTED_PRESETS:
        report(name in paths, "preset %r is shipped (file on disk)" % name)

    original = None
    active = bpy.context.window_manager.keyconfigs.active
    if active is not None:
        original = active.name

    counts = {}
    for name in EXPECTED_PRESETS:
        path = paths.get(name)
        if path is None:
            # Already reported above; activating it would only add noise.
            continue
        print("  --- preset %r" % name)
        ok, count = check_preset(name, path)
        if ok and count is not None:
            counts[name] = count

    # Restore the configuration the binary started with, so nothing downstream
    # is affected by this check having run.
    if original and original in paths:
        activate(paths[original])

    print("  preset keymap counts: %s"
          % ", ".join("%s=%d" % (k, counts[k]) for k in sorted(counts)))

    report(
        len(counts) == len(EXPECTED_PRESETS),
        "every shipped preset loaded and was measured (%s)" % (sorted(counts),),
    )

    kc = bpy.context.window_manager.keyconfigs.active
    if kc is None:
        report(False, "an active key configuration exists")
        finish()
        return None

    keymaps = list(kc.keymaps)
    print("  active configuration %r: %d keymaps" % (kc.name, len(keymaps)))

    # The failure this check was written for: a load that aborted leaves the
    # configuration present but mostly empty, which looks fine from every other
    # angle. Re-asserted on the restored configuration.
    report(
        len(keymaps) >= MINIMUM_KEYMAPS,
        "the active configuration loaded fully (%d keymaps, want >= %d)"
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


def guarded_run():
    """`run` behind a safety net.

    An exception escaping a timer callback prints a traceback and then the
    process dies of an access violation, so the exit status the harness reads is
    a crash rather than a result. That is how the `file=` typo above first
    showed up. Catching here turns any future mistake of the same kind into an
    ordinary FAIL with a readable message.
    """
    try:
        run()
    except Exception:
        import traceback
        traceback.print_exc()
        report(False, "the check ran to completion without raising")
        finish()


bpy.app.timers.register(guarded_run, first_interval=1.0)
