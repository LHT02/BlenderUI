# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows Shell COM objects. Import ONLY in the isolated helper process.

One STA owns the PIDLs, IContextMenu and HMENUs until the session ends. No COM
interface or native pointer crosses IPC. The UI receives opaque node/command IDs.
"""

import ctypes as c
from ctypes import wintypes as w
import uuid

P = c.c_void_p
HRESULT = c.c_long
ole = c.OleDLL("ole32")
shell = c.WinDLL("shell32")
user = c.WinDLL("user32")


class GUID(c.Structure):
    _fields_ = [("data", c.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__((c.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


IID_FOLDER = GUID("000214e6-0000-0000-c000-000000000046")
IID_MENU = GUID("000214e4-0000-0000-c000-000000000046")
IID_MENU2 = GUID("000214f4-0000-0000-c000-000000000046")
IID_MENU3 = GUID("bcfce0a0-ec17-11d0-8d10-00a0c90f2719")


class MenuItem(c.Structure):
    _fields_ = [("size", w.UINT), ("mask", w.UINT), ("type", w.UINT),
                ("state", w.UINT), ("id", w.UINT), ("submenu", P),
                ("checked", P), ("unchecked", P), ("data", c.c_size_t),
                ("text", w.LPWSTR), ("length", w.UINT), ("bitmap", P)]


class InvokeInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("mask", w.DWORD), ("window", P),
                ("verb", P), ("parameters", P), ("directory", P),
                ("show", c.c_int), ("hotkey", w.DWORD), ("icon", P),
                ("title", P), ("verb_w", P), ("parameters_w", P),
                ("directory_w", P), ("title_w", P), ("point", w.POINT)]


class ExecuteInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("mask", w.ULONG), ("window", P),
                ("verb", w.LPCWSTR), ("file", w.LPCWSTR), ("parameters", w.LPCWSTR),
                ("directory", w.LPCWSTR), ("show", c.c_int), ("instance", P),
                ("idlist", P), ("class_name", w.LPCWSTR), ("class_key", P),
                ("hotkey", w.DWORD), ("icon", P), ("process", P)]


def properties(path):
    info = ExecuteInfo()
    info.size, info.mask, info.show = c.sizeof(info), 0xC, 1  # SEE_MASK_INVOKEIDLIST
    info.verb, info.file = "properties", path
    if not api(shell, "ShellExecuteExW", w.BOOL, c.POINTER(ExecuteInfo))(c.byref(info)):
        raise c.WinError()


def api(dll, name, result, *args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = result, args
    return fn


parse_name = api(shell, "SHParseDisplayName", HRESULT, w.LPCWSTR, P, c.POINTER(P), w.DWORD, P)
bind_parent = api(shell, "SHBindToParent", HRESULT, P, c.POINTER(GUID), c.POINTER(P), c.POINTER(P))
create_menu = api(user, "CreatePopupMenu", P)
destroy_menu = api(user, "DestroyMenu", w.BOOL, P)
menu_count = api(user, "GetMenuItemCount", c.c_int, P)
menu_info = api(user, "GetMenuItemInfoW", w.BOOL, P, w.UINT, w.BOOL, c.POINTER(MenuItem))
free_mem = api(ole, "CoTaskMemFree", None, P)
peek = api(user, "PeekMessageW", w.BOOL, c.POINTER(w.MSG), P, w.UINT, w.UINT, w.UINT)
translate = api(user, "TranslateMessage", w.BOOL, c.POINTER(w.MSG))
dispatch = api(user, "DispatchMessageW", c.c_ssize_t, c.POINTER(w.MSG))


def method(ptr, slot, result, *args):
    table = c.cast(ptr, c.POINTER(c.POINTER(P))).contents
    return c.WINFUNCTYPE(result, P, *args)(table[slot])


def check(hr, operation):
    if hr < 0:
        raise OSError("%s failed (0x%08X)" % (operation, hr & 0xFFFFFFFF))


def release(ptr):
    if ptr:
        method(ptr, 2, w.ULONG)(ptr)


def query(ptr, iid):
    result = P()
    hr = method(ptr, 0, HRESULT, c.POINTER(GUID), c.POINTER(P))(ptr, c.byref(iid), c.byref(result))
    return result if hr >= 0 else P()


def pump():
    msg = w.MSG()
    while peek(c.byref(msg), None, 0, 0, 1):
        translate(c.byref(msg))
        dispatch(c.byref(msg))


class ShellMenu:
    def __init__(self, paths):
        self.pidls = []
        self.folder = P()
        self.context = P()
        self.context2 = P()
        self.context3 = P()
        self.menu = None
        self.nodes = {}
        self.commands = set()
        try:
            children = []
            for path in paths:
                pidl = P()
                check(parse_name(path, None, c.byref(pidl), 0, None), "Resolve file")
                self.pidls.append(pidl)
                parent, child = P(), P()
                check(bind_parent(pidl, c.byref(IID_FOLDER), c.byref(parent), c.byref(child)), "Bind folder")
                if not self.folder:
                    self.folder = parent
                else:
                    release(parent)
                children.append(child.value)
            if not children:
                raise ValueError("No files selected")
            array = (P * len(children))(*children)
            check(method(self.folder, 10, HRESULT, P, w.UINT, c.POINTER(P),
                         c.POINTER(GUID), P, c.POINTER(P))(
                             self.folder, None, len(children), array, c.byref(IID_MENU),
                             None, c.byref(self.context)), "Get system menu")
            self.context3 = query(self.context, IID_MENU3)
            self.context2 = query(self.context, IID_MENU2) if not self.context3 else P()
            self.menu = create_menu()
            if not self.menu:
                raise c.WinError()
            check(method(self.context, 3, HRESULT, P, w.UINT, w.UINT, w.UINT, w.UINT)(
                self.context, self.menu, 0, 1, 0x7FFF, 4), "Build system menu")  # CMF_EXPLORE
            self.nodes["root"] = (self.menu, 0)
        except BaseException:
            self.close()
            raise

    def items(self, node="root"):
        if node not in self.nodes:
            raise ValueError("This submenu is no longer available")
        menu, position = self.nodes[node]
        # WM_INITMENUPOPUP is a synchronous owner-window message. Forward it
        # explicitly before reading a delayed submenu (7-Zip/TortoiseSVN).
        if node != "root":
            result = c.c_ssize_t()
            if self.context3:
                method(self.context3, 7, HRESULT, w.UINT, c.c_size_t, c.c_ssize_t,
                       c.POINTER(c.c_ssize_t))(
                           self.context3, 0x117, menu, position, c.byref(result))
            elif self.context2:
                method(self.context2, 6, HRESULT, w.UINT, c.c_size_t, c.c_ssize_t)(
                    self.context2, 0x117, menu, position)
        rows = []
        for index in range(max(0, menu_count(menu))):
            text = c.create_unicode_buffer(1024)
            item = MenuItem()
            item.size = c.sizeof(item)
            item.mask = 0x147  # STATE | ID | SUBMENU | STRING | FTYPE
            item.text, item.length = c.cast(text, w.LPWSTR), len(text)
            if not menu_info(menu, index, True, c.byref(item)):
                continue
            key = "%s/%d" % (node, index)
            label = text.value.replace("&&", "\0").replace("&", "").replace("\0", "&")
            row = {"label": label, "enabled": not bool(item.state & 3),
                   "separator": bool(item.type & 0x800), "id": int(item.id)}
            if item.submenu:
                self.nodes[key] = (item.submenu, index)
                row["submenu"] = key
            elif not row["separator"] and row["enabled"] and 1 <= item.id <= 0x7FFF:
                self.commands.add(item.id)
            if row["separator"] or label or item.submenu:
                rows.append(row)
        return rows

    def invoke(self, command):
        if command not in self.commands:
            raise ValueError("Command does not belong to this menu session")
        info = InvokeInfo()
        info.size, info.mask, info.show = c.sizeof(info), 0x4000, 1  # CMIC_MASK_UNICODE
        info.verb = info.verb_w = command - 1
        check(method(self.context, 4, HRESULT, c.POINTER(InvokeInfo))(
            self.context, c.byref(info)), "Run system command")

    def close(self):
        if self.menu:
            destroy_menu(self.menu)
            self.menu = None
        for name in ("context3", "context2", "context", "folder"):
            release(getattr(self, name))
            setattr(self, name, P())
        for pidl in self.pidls:
            free_mem(pidl)
        self.pidls.clear()
