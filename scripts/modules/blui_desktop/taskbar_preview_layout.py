# SPDX-License-Identifier: GPL-2.0-or-later
"""Physical-pixel taskbar preview geometry; no bpy or native window calls."""
import math

MAX_PREVIEWS = 4


def preview_layout(count, available_width, *, scale=1.0):
    """Return bounded cards and thumbnail slots in top-left client coordinates."""
    if type(count) is not int or not 0 <= count <= 256:
        raise ValueError('Invalid preview count')
    if type(available_width) is not int or not 32 <= available_width <= 32768:
        raise ValueError('Invalid preview display width')
    if (type(scale) not in (int, float) or not math.isfinite(scale) or
            not 0.5 <= scale <= 8):
        raise ValueError('Invalid preview display scale')
    margin = min(max(2, round(8 * scale)), (available_width - 4) // 2)
    gap, title = max(2, round(8 * scale)), round(28 * scale)
    count = min(count, MAX_PREVIEWS)
    # On narrow or high-DPI monitors show fewer cards rather than overflow.
    minimum = max(16, round(96 * scale))
    count = min(count, max(1, (available_width - 2 * margin + gap) // (minimum + gap)))
    if not count:
        return {'width': min(available_width, 240), 'height': max(32, title + 2 * margin),
                'count': 0, 'card_rects': [], 'rects': []}
    usable = max(count, available_width - 2 * margin - (count - 1) * gap)
    card_width = min(round(240 * scale), usable // count)
    thumb_height = max(8, round(132 * scale))
    width = 2 * margin + count * card_width + (count - 1) * gap
    height = 2 * margin + title + thumb_height
    cards, slots = [], []
    for index in range(count):
        left = margin + index * (card_width + gap)
        cards.append([left, margin, left + card_width, height - margin])
        slots.append([left, margin + title, left + card_width, height - margin])
    return {'width': width, 'height': height, 'count': count, 'card_rects': cards, 'rects': slots}


def checked_rect(value):
    if (not isinstance(value, (tuple, list)) or len(value) != 4 or
            not all(type(item) is int and 0 <= item <= 32768 for item in value) or
            value[0] >= value[2] or value[1] >= value[3]):
        raise ValueError('Invalid preview client rectangle')
    return tuple(value)


def fit_rect(source_size, slot):
    """Aspect fit a live window, never stretch its pixels or exceed its slot."""
    slot = checked_rect(slot)
    if (not isinstance(source_size, (tuple, list)) or len(source_size) != 2 or
            not all(type(item) is int and 0 < item <= 32768 for item in source_size)):
        raise ValueError('Invalid preview source size')
    width, height = source_size
    factor = min((slot[2] - slot[0]) / width, (slot[3] - slot[1]) / height)
    fitted_width, fitted_height = max(1, round(width * factor)), max(1, round(height * factor))
    left = slot[0] + ((slot[2] - slot[0]) - fitted_width) // 2
    top = slot[1] + ((slot[3] - slot[1]) - fitted_height) // 2
    return (left, top, left + fitted_width, top + fitted_height)
