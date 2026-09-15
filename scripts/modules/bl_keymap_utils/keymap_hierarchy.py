# SPDX-License-Identifier: GPL-2.0-or-later

__all__ = (
    "generate",
)


def _km_expand_from_toolsystem(space_type, context_mode):
    def _fn():
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        for cls in ToolSelectPanelHelper.__subclasses__():
            if cls.bl_space_type == space_type:
                return cls.keymap_ui_hierarchy(context_mode)
        raise Exception("keymap not found")
    return _fn


def _km_hierarchy_iter_recursive(items):
    for sub in items:
        if callable(sub):
            yield from sub()
        else:
            yield (*sub[:3], list(_km_hierarchy_iter_recursive(sub[3])))


def generate():
    return list(_km_hierarchy_iter_recursive(_km_hierarchy))


# bpy.type.KeyMap: (km.name, km.space_type, km.region_type, [...])

#    ('Script', 'EMPTY', 'WINDOW', []),


# BLUI's keymap tree.
#
# `space_type` here is validated against `rna_enum_space_type_items` when the
# keymap is created, so an entry naming an editor BLUI does not have (the 3D
# viewport, graph editor, dope sheet, NLA, timeline, outliner, node editor,
# properties, clip editor) would raise rather than merely be unused. Those
# entries are gone; what remains is the tree for the editors BLUI does have.
#
# Access via 'km_hierarchy'.
_km_hierarchy = [
    ('Window', 'EMPTY', 'WINDOW', []),  # file save, window change, exit
    ('Screen', 'EMPTY', 'WINDOW', [     # full screen, undo, screenshot
        ('Screen Editing', 'EMPTY', 'WINDOW', []),    # re-sizing, action corners
        ('Region Context Menu', 'EMPTY', 'WINDOW', []),      # header/footer/navigation_bar stuff (per region)
    ]),

    ('View2D', 'EMPTY', 'WINDOW', []),    # view 2d navigation (per region)
    ('View2D Buttons List', 'EMPTY', 'WINDOW', []),  # view 2d with buttons navigation

    ('User Interface', 'EMPTY', 'WINDOW', []),

    ('Image', 'IMAGE_EDITOR', 'WINDOW', [
        # Image (reverse order, UVEdit before Image).
        ('UV Editor', 'EMPTY', 'WINDOW', [
            _km_expand_from_toolsystem('IMAGE_EDITOR', 'UV'),
        ]),
        ('UV Sculpt', 'EMPTY', 'WINDOW', []),
        # Image and view3d.
        ('Image Paint', 'EMPTY', 'WINDOW', [
            _km_expand_from_toolsystem('IMAGE_EDITOR', 'PAINT'),
        ]),
        ('Image View', 'IMAGE_EDITOR', 'WINDOW', [
            _km_expand_from_toolsystem('IMAGE_EDITOR', 'VIEW'),
        ]),
        ('Image Generic', 'IMAGE_EDITOR', 'WINDOW', [
            _km_expand_from_toolsystem('IMAGE_EDITOR', None),
        ]),
    ]),

    ('SequencerCommon', 'SEQUENCE_EDITOR', 'WINDOW', [
        ('Sequencer', 'SEQUENCE_EDITOR', 'WINDOW', [
            _km_expand_from_toolsystem('SEQUENCE_EDITOR', 'SEQUENCER'),
        ]),
        ('SequencerPreview', 'SEQUENCE_EDITOR', 'WINDOW', [
            _km_expand_from_toolsystem('SEQUENCE_EDITOR', 'PREVIEW'),
        ]),
    ]),

    ('File Browser', 'FILE_BROWSER', 'WINDOW', [
        ('File Browser Main', 'FILE_BROWSER', 'WINDOW', []),
        ('File Browser Buttons', 'FILE_BROWSER', 'WINDOW', []),
    ]),

    ('Info', 'INFO', 'WINDOW', []),

    ('Text', 'TEXT_EDITOR', 'WINDOW', [
        ('Text Generic', 'TEXT_EDITOR', 'WINDOW', []),
    ]),
    ('Console', 'CONSOLE', 'WINDOW', []),

    ('Mask Editing', 'EMPTY', 'WINDOW', []),
    ('Frames', 'EMPTY', 'WINDOW', []),    # frame navigation (per region)
    ('Markers', 'EMPTY', 'WINDOW', []),    # markers (per region)
    ('Animation', 'EMPTY', 'WINDOW', []),    # frame change on click, preview range (per region)
    ('Animation Channels', 'EMPTY', 'WINDOW', []),

    ('Gesture Straight Line', 'EMPTY', 'WINDOW', []),
    ('Gesture Zoom Border', 'EMPTY', 'WINDOW', []),
    ('Gesture Box', 'EMPTY', 'WINDOW', []),

    ('Standard Modal Map', 'EMPTY', 'WINDOW', []),
    ('Transform Modal Map', 'EMPTY', 'WINDOW', []),
    ('Eyedropper Modal Map', 'EMPTY', 'WINDOW', []),
    ('Eyedropper ColorRamp PointSampling Map', 'EMPTY', 'WINDOW', []),
]
