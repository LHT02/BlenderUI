# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure responsive dimensions for the fixed Start shell window and its scroll list."""
import math

MAX_ROWS = 21
UNIT = 20


def metrics(region_height, ui_scale, *, empty=False):
    if (isinstance(region_height, bool) or not isinstance(region_height, (int, float)) or
            not math.isfinite(region_height) or region_height < 0):
        raise ValueError('Invalid Start menu region height')
    if (isinstance(ui_scale, bool) or not isinstance(ui_scale, (int, float)) or
            not math.isfinite(ui_scale) or ui_scale <= 0):
        raise ValueError('Invalid Start menu UI scale')
    logical = min(10000, region_height / ui_scale)
    reserve = 166 + (20 if empty else 0)
    rows = max(1, min(MAX_ROWS, int(max(0, logical - reserve) // UNIT)))
    compact = logical < 340
    tiny = logical < 260
    hidden = {'MUSIC', 'DOWNLOADS'} if compact else set()
    if tiny:
        hidden.update({'DOCUMENTS', 'PICTURES', 'CONTROL_PANEL'})
    # Nine normal action rows include Refresh. Fold secondary locations into a
    # menu when screen clamping/large UI text leaves fewer logical pixels.
    action_rows = 9 - len(hidden) + bool(hidden)
    row_scale = 1.0 if compact else min(1.5, max(1.0, (logical - 124) / (9 * UNIT)))
    user_scale = 1.0 if tiny else 1.5 if compact else 2.1
    separator = .6 if compact else 1.3
    right_used = action_rows * UNIT * row_scale + UNIT * user_scale + 20 * separator + 50
    target = min(max(0, logical - 30), rows * UNIT + reserve)
    spacer_units = max(0, (target - right_used) / UNIT)
    return {'rows': rows, 'row_scale': row_scale, 'user_scale': user_scale,
            'separator': separator, 'spacer_units': spacer_units, 'hidden': hidden}


def owns_context_child(token, windows, menu_state):
    """Only immutable source identities of live, owned Start-app children count."""
    for window in windows:
        if getattr(window, 'blui_shell_role', '') != 'TASK_CHOOSER':
            continue
        state = menu_state(window)
        source = state.get('source')
        if (state.get('kind') == 'START_APP' and isinstance(source, (tuple, list)) and
                len(source) == 2 and tuple(source) == token):
            return True
    return False
