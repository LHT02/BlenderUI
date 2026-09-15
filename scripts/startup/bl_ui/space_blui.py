# SPDX-License-Identifier: GPL-2.0-or-later
"""BLUI's own editor headers.

BLUI has no top bar. Blender's top bar holds the workspace tabs and the
scene / view-layer switchers, which exist because Blender is one document that
you switch modes within. BLUI components are separate windows rather than modes,
so there is nothing for those controls to switch between.

The File / Edit / Window / Help menus lived in that top bar too, so they move
into each component's own header, which is where someone using a file browser
expects to find them anyway.

The reports banner rides along because BLUI also drops the status bar, and
without either of them an operator error ("Cannot do that here") would have
nowhere to appear.
"""

from bpy.types import Header

from bl_ui.space_topbar import TOPBAR_MT_editor_menus

# The space types BLUI ships. Keep in sync with the BLUI workspace set in
# release/datafiles/startup.blend (see blui/tools/build_blui_startup.py).
BLUI_SPACE_TYPES = (
    "FILE_BROWSER",
    "IMAGE_EDITOR",
    "TEXT_EDITOR",
    "SEQUENCE_EDITOR",
    "CONSOLE",
    "PREFERENCES",
)


def _draw_blui_menus(self, context):
    layout = self.layout

    TOPBAR_MT_editor_menus.draw_collapsible(context, layout)
    layout.separator()

    # Feedback that used to live in the status bar.
    layout.template_reports_banner()
    layout.template_running_jobs()


def _make_header(space_type):
    return type(
        "BLUI_HT_menus_%s" % space_type,
        (Header,),
        {
            "bl_space_type": space_type,
            "bl_region_type": "HEADER",
            "draw": _draw_blui_menus,
            "__doc__": "BLUI application menus, drawn in the %s header." % space_type,
        },
    )


classes = tuple(_make_header(space_type) for space_type in BLUI_SPACE_TYPES)

del _make_header
