# SPDX-License-Identifier: GPL-2.0-or-later
"""Check which preferences BLUI offers.

Blender's preferences are a 3D authoring tool's preferences. BLUI's are a file
browser's, an image viewer's and a text editor's. This checks that the panel set
matches, so a panel about objects, sculpting, animation or a `.blend` container
cannot quietly come back.

Run:
    build\\bin\\BLUI.exe --background --factory-startup \
        --python source\\blui\\tools\\check_preferences.py

Exits non-zero when the preferences are not what BLUI intends.
"""

import sys

import bpy

# The sections BLUI keeps. Everything Blender has that is not here (Viewport,
# Animation, Lights, Navigation, Experimental, ...) was removed from
# `rna_enum_preference_section_items`, so a panel in one of those can never be
# drawn - and should not be registered either.
SECTIONS = {
    # A panel with no context draws above the section list, whatever is
    # selected; that is how "Save Preferences" and the navigation bar work.
    "",
    "interface",
    "themes",
    "editing",
    "input",
    "keymap",
    "system",
    "save_load",
    "file_paths",
    "addons",
}

# The panels BLUI expects inside the sections it reworked. The Auto Run panel is
# declared in `file_paths` although its name starts with `saveload_`.
EXPECTED = {
    "editing": {"USERPREF_PT_edit_text_editor"},
    "save_load": {"USERPREF_PT_saveload_blend", "USERPREF_PT_saveload_file_browser"},
    "file_paths": {
        "USERPREF_PT_file_paths_applications",
        "USERPREF_PT_file_paths_data",
        "USERPREF_PT_file_paths_script_directories",
        "USERPREF_PT_saveload_autorun",
    },
}

# Sections Blender has that BLUI removed wholesale. Their panels must not be
# registered at all, not merely unreachable.
DROPPED = ["animation", "experimental", "lights", "navigation", "viewport"]

failures = []


def report(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        failures.append(message)


def all_panel_classes():
    """Every registered Panel subclass, including ones behind a mixin."""
    seen = set()
    stack = list(bpy.types.Panel.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
    return seen


panels = {}
for cls in all_panel_classes():
    if getattr(cls, "is_registered", False) and getattr(cls, "bl_space_type", None) == "PREFERENCES":
        panels.setdefault(getattr(cls, "bl_context", ""), set()).add(cls.__name__)

print("BLUI preferences")
for section in sorted(panels):
    print("  %-12s %s" % (section, ", ".join(sorted(panels[section]))))

for section in sorted(panels):
    report(section in SECTIONS, "section %r is one BLUI keeps" % section)

for section in DROPPED:
    report(section not in panels, "dropped section %r has no registered panel" % section)

for section, expected in EXPECTED.items():
    actual = panels.get(section, set())
    report(
        actual == expected,
        "%s is exactly %s (got %s)" % (section, sorted(expected), sorted(actual)),
    )

print("")
if failures:
    print("check_preferences: FAILED (%d)" % len(failures))
    sys.exit(1)
print("check_preferences: PASS")
