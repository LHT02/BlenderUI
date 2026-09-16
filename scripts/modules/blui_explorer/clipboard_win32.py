# SPDX-License-Identifier: GPL-2.0-or-later
"""Clear a completed cut only if nobody has replaced the clipboard meanwhile."""
import ctypes


def sequence():
    return ctypes.windll.user32.GetClipboardSequenceNumber()


def clear_if_unchanged(expected):
    api = ctypes.windll.user32
    if not expected or not api.OpenClipboard(None):
        return False
    try:
        return bool(api.EmptyClipboard()) if sequence() == expected else False
    finally:
        api.CloseClipboard()
