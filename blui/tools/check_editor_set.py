# SPDX-License-Identifier: GPL-2.0-or-later
"""Check which editors BLUI actually offers.

The editor-type menu is driven by `rna_enum_space_type_items`, and a space type
is only usable if it is also registered by `ED_spacetypes_init()`. This checks
both halves, and that none of the Blender editors BLUI dropped can be reached.

Run:
    build\\bin\\BLUI.exe --background --factory-startup \
        --python source\\blui\\tools\\check_editor_set.py

Exits non-zero when the editor set is not what BLUI intends.
"""

import sys

import bpy

# What BLUI is: the six components. `EMPTY` is the "no editor yet" state Python
# can read, and Info / Top Bar / Status Bar are machinery that is named in the
# enum but never offered as an editor.
COMPONENTS = [
    "FILE_BROWSER",
    "IMAGE_EDITOR",
    "SEQUENCE_EDITOR",
    "TEXT_EDITOR",
    "CONSOLE",
    "PREFERENCES",
]
MACHINERY = ["EMPTY", "INFO", "TOPBAR", "STATUSBAR"]

# Editors that exist in Blender 3.6 and must not be reachable in BLUI.
REMOVED = [
    "VIEW_3D",
    "NODE_EDITOR",
    "CLIP_EDITOR",
    "DOPESHEET_EDITOR",
    "GRAPH_EDITOR",
    "NLA_EDITOR",
    "OUTLINER",
    "PROPERTIES",
    "SPREADSHEET",
]

failures = []


def report(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        failures.append(message)


def enum_ids(prop):
    return [item.identifier for item in prop.enum_items]


print("BLUI editor set")

# 1. What `Area.type` / `Area.ui_type` and `Panel.bl_space_type` accept.
area_type = enum_ids(bpy.types.Area.bl_rna.properties["type"])
print("  Area.type enum: %s" % ", ".join(area_type))

for identifier in COMPONENTS:
    report(identifier in area_type, "component %r is an area type" % identifier)
for identifier in REMOVED:
    report(identifier not in area_type, "removed editor %r is not an area type" % identifier)

# 2. What the editor-type menu operator offers. This is the same array, but
#    checking it catches a mismatch between the menu and the property.
def operator_rna():
    try:
        return bpy.ops.screen.space_type_set_or_cycle.get_rna_type()
    except AttributeError:
        return None


ot = operator_rna()
if ot is None:
    report(False, "SCREEN_OT_space_type_set_or_cycle is registered")
else:
    op_type = enum_ids(ot.properties["space_type"])
    print("  editor-type menu: %s" % ", ".join(op_type))
    for identifier in REMOVED:
        report(identifier not in op_type, "removed editor %r is not in the menu" % identifier)
    for identifier in COMPONENTS:
        report(identifier in op_type, "component %r is in the menu" % identifier)

# 3. A panel can only be registered for a space type that exists in that array,
#    so this is the same list - checked because getting it wrong takes the whole
#    UI down at startup rather than failing loudly.
panel_type = enum_ids(bpy.types.Panel.bl_rna.properties["bl_space_type"])
for identifier in REMOVED:
    report(identifier not in panel_type, "removed editor %r cannot host a panel" % identifier)

# 4. Every area in the startup file must be one BLUI offers, and between them
#    they must cover the six components. This is the check that the offered
#    editors actually instantiate rather than merely being named.
seen = {}
for workspace in bpy.data.workspaces:
    for screen in workspace.screens:
        for area in screen.areas:
            seen.setdefault(area.type, []).append(workspace.name)

print("  areas in the startup file: %s" % ", ".join(sorted(seen)))
for identifier in sorted(seen):
    report(identifier in COMPONENTS, "area type %r is a BLUI component" % identifier)
for identifier in COMPONENTS:
    report(identifier in seen, "component %r has a workspace" % identifier)

print("")
if failures:
    print("check_editor_set: FAILED (%d)" % len(failures))
    sys.exit(1)
print("check_editor_set: PASS")
