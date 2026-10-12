# SPDX-License-Identifier: GPL-2.0-or-later
"""Build one folder association scope, inside its isolated STA helper only."""
import ctypes as c
import winreg

if __package__:
    from . import shell_win32 as win
else:
    import shell_win32 as win


class DefaultContext(c.Structure):
    _fields_ = [('window', win.P), ('callback', win.P), ('parent', win.P),
                ('folder', win.P), ('count', win.w.UINT), ('children', c.POINTER(win.P)),
                ('associations', win.P), ('key_count', win.w.UINT), ('keys', c.POINTER(win.P))]


SCOPES = {'folder': ('Folder', 'AllFilesystemObjects'), 'directory': ('Directory',)}


def create_context(folder, children, result, scope):
    # Read existing association keys only; do not disable/re-register any extension.
    keys = []
    try:
        for name in SCOPES[scope]:
            try:
                keys.append(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name))
            except FileNotFoundError:
                continue
        if not keys:
            raise RuntimeError('Folder menu associations are unavailable')
        assert len(keys) <= 16  # DEFCONTEXTMENU's documented hard limit.
        handles = (win.P * len(keys))(*(int(key) for key in keys))
        info = DefaultContext()
        info.folder, info.count, info.children = folder, len(children), children
        info.key_count, info.keys = len(keys), handles
        create = win.api(win.shell, 'SHCreateDefaultContextMenu', win.HRESULT,
                         c.POINTER(DefaultContext), c.POINTER(win.GUID), c.POINTER(win.P))
        # The real parent IShellFolder and relative child PIDLs preserve exact targets.
        win.check(create(c.byref(info), c.byref(win.IID_MENU), c.byref(result)), 'Get folder menu')
        return keys
    except Exception:
        for key in keys:
            key.Close()
        raise
