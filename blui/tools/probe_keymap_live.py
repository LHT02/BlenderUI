# SPDX-License-Identifier: GPL-2.0-or-later
"""Report the key bindings for `file.clipboard_*` in the config BLUI actually loads.

This exists because the rest of the suite runs with `--factory-startup`, which
makes Blender build its keymaps from the Python defaults and ignore
`userpref.blend` entirely. A saved userpref also carries a saved copy of every
keymap, and that saved copy is what a normal launch uses - so a binding added to
`keymap_data/blender_default.py` can be present in every check and still be
missing from the application a person is looking at.

Run both ways and compare:

    BLUI.exe --factory-startup --python blui/tools/probe_keymap_live.py
    BLUI.exe --python blui/tools/probe_keymap_live.py
"""

import bpy

WANTED = ("file.clipboard_copy", "file.clipboard_cut", "file.clipboard_paste")

kc = bpy.context.window_manager.keyconfigs.user or bpy.context.window_manager.keyconfigs.active
print("KEYMAP: config=%r  factory_startup=%s"
      % (kc.name, bpy.app.factory_startup))

found = {}
for km in kc.keymaps:
    for kmi in km.keymap_items:
        if kmi.idname in WANTED:
            found.setdefault(kmi.idname, []).append((km.name, kmi.type, kmi.ctrl))

for op in WANTED:
    hits = found.get(op)
    if hits:
        print("KEYMAP:   OK   %-24s %s" % (op, ", ".join("%s(%s ctrl=%s)" % h for h in hits)))
    else:
        print("KEYMAP:   MISS %-24s not bound in this configuration" % op)

print("KEYMAP: RESULT %s" % ("ALL-BOUND" if len(found) == len(WANTED) else "MISSING-BINDINGS"))

# A normal launch opens a window and would sit there forever, which is how this
# probe first hung for minutes. It has nothing to show, so it leaves by itself.
import sys
sys.stdout.flush()
bpy.ops.wm.quit_blender()
