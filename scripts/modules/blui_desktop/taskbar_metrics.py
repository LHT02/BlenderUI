# SPDX-License-Identifier: GPL-2.0-or-later
"""Logical taskbar dimensions shared by native placement and UI layout."""
import math

BAR_HEIGHT = 56
BUTTON_SIZE = 40
SIDE_UNITS = 4.8
UI_UNIT = 20
MAX_ICONS = 64


def icon_capacity(width, ui_scale, *, icon_size=32, side_width=SIDE_UNITS * UI_UNIT):
    """Fit app buttons, keeping both side blocks, Start and overflow available.

    ``width`` is the region width in pixels; ``ui_scale`` converts logical UI
    dimensions to pixels. Reserve the overflow button even when it is absent,
    so admitting one more app never suddenly clips the clock/settings block.
    """
    if (isinstance(width, bool) or not isinstance(width, (int, float)) or
            not math.isfinite(width) or width < 0):
        raise ValueError('Invalid taskbar width')
    if (isinstance(ui_scale, bool) or not isinstance(ui_scale, (int, float)) or
            not math.isfinite(ui_scale) or ui_scale <= 0):
        raise ValueError('Invalid taskbar UI scale')
    logical_width = width / ui_scale
    if type(icon_size) is not int or not 16 <= icon_size <= 64:
        raise ValueError('Invalid taskbar icon size')
    if type(side_width) not in (int, float) or not math.isfinite(side_width) or side_width < 0:
        raise ValueError('Invalid taskbar side width')
    button = icon_size + 8
    reserved = 2 * side_width + 2 * button
    if logical_width >= reserved + MAX_ICONS * button:
        return MAX_ICONS
    return max(1, min(MAX_ICONS, int(max(0, logical_width - reserved) // button)))
