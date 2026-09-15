# SPDX-License-Identifier: GPL-2.0-or-later
"""Report the workspace set of whatever startup file BLUI loaded.

Run with:
    BLUI.exe --background --factory-startup --python tools/verify_startup.py
"""

import bpy


def main():
    print("VERIFY: version=%s" % bpy.app.version_string)
    names = [w.name for w in bpy.data.workspaces]
    print("VERIFY: workspaces(%d)=%s" % (len(names), names))
    for workspace in bpy.data.workspaces:
        for screen in workspace.screens:
            areas = []
            for area in screen.areas:
                active = area.spaces.active
                areas.append("%s/%s" % (area.type, active.type if active else None))
            print("VERIFY:   %-9s areas=%s" % (workspace.name, areas))
    print("VERIFY: done")


main()
