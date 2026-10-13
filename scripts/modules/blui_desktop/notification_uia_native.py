# SPDX-License-Identifier: GPL-2.0-or-later
"""Small SDK-defined UIA COM client, used only by the notification helper thread.

No global desktop search, pointer injection or synthesized mouse clicks. Vtable
slots follow Windows SDK UIAutomationClient.h; every returned interface is owned.
"""
import ctypes as c
from ctypes import wintypes as w
import uuid

HRESULT = c.c_long
CALL = getattr(c, 'WINFUNCTYPE', c.CFUNCTYPE)
INVOKE = (10000, 'fb377fbe-8ea6-46d5-9c73-6499642d3059', 3)
LEGACY = (10018, '828055ad-355b-4435-86d5-3b51c14a9b1b', 4)


class GUID(c.Structure):
    _fields_ = [('data', c.c_ubyte * 16)]

    @classmethod
    def from_text(cls, value):
        return cls((c.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


def call(pointer, slot, result, arguments, *values):
    if not pointer or not pointer.value:
        raise ValueError('UI Automation interface is unavailable')
    table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    function = CALL(result, c.c_void_p, *arguments)(table[slot])
    return function(pointer, *values)


def checked(status):
    if status < 0:
        raise OSError('UI Automation provider failed (0x%08x)' % (status & 0xffffffff))


def release(pointer):
    if pointer and pointer.value:
        call(pointer, 2, w.ULONG, [])
        pointer.value = None


class Session:
    def __init__(self):
        self.ole = c.WinDLL('ole32', use_last_error=True)
        self.automation = c.WinDLL('oleaut32', use_last_error=True)
        self.ole.CoInitializeEx.argtypes, self.ole.CoInitializeEx.restype = [c.c_void_p, w.DWORD], HRESULT
        self.ole.CoUninitialize.argtypes, self.ole.CoUninitialize.restype = [], None
        self.ole.CoCreateInstance.argtypes = [c.POINTER(GUID), c.c_void_p, w.DWORD, c.POINTER(GUID), c.POINTER(c.c_void_p)]
        self.ole.CoCreateInstance.restype = HRESULT
        checked(self.ole.CoInitializeEx(None, 0))  # Dedicated MTA thread; never Blender's apartment.
        self.opened, self.client, self.walker = True, c.c_void_p(), c.c_void_p()
        for name, result, args in (
            ('SysStringLen', w.UINT, [c.c_void_p]), ('SysFreeString', None, [c.c_void_p]),
            ('SafeArrayGetLBound', HRESULT, [c.c_void_p, w.UINT, c.POINTER(w.LONG)]),
            ('SafeArrayGetUBound', HRESULT, [c.c_void_p, w.UINT, c.POINTER(w.LONG)]),
            ('SafeArrayAccessData', HRESULT, [c.c_void_p, c.POINTER(c.c_void_p)]),
            ('SafeArrayUnaccessData', HRESULT, [c.c_void_p]), ('SafeArrayDestroy', HRESULT, [c.c_void_p]),
        ):
            function = getattr(self.automation, name)
            function.restype, function.argtypes = result, args
        try:
            try:
                self.client = self.create('e22ad333-b25f-460c-83d0-0581107395c9', '34723aff-0c9d-49d0-9896-7ab52df8cd8a')
                # CUIAutomation8 implements IUIAutomation2 timeouts. These are
                # limits, not permission to traverse unrelated applications.
                checked(call(self.client, 61, HRESULT, [w.DWORD], 300))
                checked(call(self.client, 63, HRESULT, [w.DWORD], 300))
            except OSError:
                release(self.client)
                self.client = self.create('ff48dba4-60ef-4201-aa87-54103eef594e', '30cbe57d-d9d0-452a-ab13-7ac5ac4825ee')
            # Raw view is required to observe an already-existing offscreen
            # overflow toolbar. Traversal remains bounded to verified Explorer
            # notification roots and concrete icon-control subtrees.
            checked(call(self.client, 16, HRESULT, [c.POINTER(c.c_void_p)], c.byref(self.walker)))
        except Exception:
            self.close()
            raise

    def create(self, class_id, interface_id, *, context=1):
        result = c.c_void_p()
        checked(self.ole.CoCreateInstance(c.byref(GUID.from_text(class_id)), None, context,
                                         c.byref(GUID.from_text(interface_id)), c.byref(result)))
        return result

    def element(self, handle):
        result = c.c_void_p()
        checked(call(self.client, 6, HRESULT, [w.HWND, c.POINTER(c.c_void_p)], handle, c.byref(result)))
        return result

    def child(self, element, *, sibling=False):
        result = c.c_void_p()
        checked(call(self.walker, 6 if sibling else 4, HRESULT,
                     [c.c_void_p, c.POINTER(c.c_void_p)], element, c.byref(result)))
        return result

    @staticmethod
    def integer(element, slot):
        result = c.c_int()
        checked(call(element, slot, HRESULT, [c.POINTER(c.c_int)], c.byref(result)))
        return result.value

    def text(self, element, slot, maximum=256):
        result = c.c_void_p()
        checked(call(element, slot, HRESULT, [c.POINTER(c.c_void_p)], c.byref(result)))
        try:
            length = self.automation.SysStringLen(result)
            if length > maximum:
                raise ValueError('UI Automation text is too long')
            return c.wstring_at(result, length) if result.value else ''
        finally:
            self.automation.SysFreeString(result)

    def runtime_id(self, element):
        array, data = c.c_void_p(), c.c_void_p()
        checked(call(element, 4, HRESULT, [c.POINTER(c.c_void_p)], c.byref(array)))
        if not array.value:
            raise ValueError('UI Automation element has no stable runtime identity')
        accessed = False
        try:
            low, high = w.LONG(), w.LONG()
            checked(self.automation.SafeArrayGetLBound(array, 1, c.byref(low)))
            checked(self.automation.SafeArrayGetUBound(array, 1, c.byref(high)))
            if not 1 <= high.value - low.value + 1 <= 32:
                raise ValueError('Invalid UI Automation runtime identity')
            checked(self.automation.SafeArrayAccessData(array, c.byref(data)))
            accessed = True
            return tuple(c.cast(data, c.POINTER(c.c_int))[index]
                         for index in range(high.value - low.value + 1))
        finally:
            if accessed:
                self.automation.SafeArrayUnaccessData(array)
            self.automation.SafeArrayDestroy(array)

    def action_pattern(self, element):
        for pattern, interface, slot in (INVOKE, LEGACY):
            result = c.c_void_p()
            status = call(element, 14, HRESULT, [c.c_int, c.POINTER(GUID), c.POINTER(c.c_void_p)],
                          pattern, c.byref(GUID.from_text(interface)), c.byref(result))
            if status >= 0 and result.value:
                if pattern == LEGACY[0]:
                    # The MSAA bridge sometimes exposes a pattern with no actual
                    # default action. Do not make that look like a working button.
                    try:
                        available = bool(self.text(result, 15))
                    except (OSError, ValueError):
                        available = False
                    if not available:
                        release(result)
                        continue
                return result, slot
            release(result)
        return None, None

    def expansion_state(self, element):
        result = c.c_void_p()
        status = call(element, 14, HRESULT, [c.c_int, c.POINTER(GUID), c.POINTER(c.c_void_p)],
                      10005, c.byref(GUID.from_text('619be086-1f4e-4ee4-bafa-210128738730')), c.byref(result))
        try:
            if status < 0 or not result.value:
                return None
            return self.integer(result, 5)
        finally:
            release(result)

    def describe(self, element):
        handle, rect = w.HWND(), w.RECT()
        checked(call(element, 36, HRESULT, [c.POINTER(w.HWND)], c.byref(handle)))
        checked(call(element, 43, HRESULT, [c.POINTER(w.RECT)], c.byref(rect)))
        return {'pid': self.integer(element, 20), 'type': self.integer(element, 21),
                'name': self.text(element, 23, 512)[:127], 'enabled': bool(self.integer(element, 28)),
                'id': self.text(element, 29), 'class': self.text(element, 30),
                'runtime': self.runtime_id(element), 'handle': int(handle.value or 0),
                'rect': (rect.left, rect.top, rect.right, rect.bottom)}

    def close(self):
        release(self.walker)
        release(self.client)
        if self.opened:
            self.ole.CoUninitialize()
            self.opened = False
