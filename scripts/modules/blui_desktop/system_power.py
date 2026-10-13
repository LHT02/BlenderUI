# SPDX-License-Identifier: GPL-2.0-or-later
"""Worker-only power detection and explicitly confirmed actions.

SYSTEM_POWER_CAPABILITIES follows the current Windows SDK. A reduced Fast
Startup hiberfile is not sufficient for user-requested S4 hibernation. Detection
never calls powercfg or changes the machine's hibernation configuration.
"""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import os


class _BatteryScale(c.Structure):
    _fields_ = [('granularity', w.DWORD), ('capacity', w.DWORD)]


class _Capabilities(c.Structure):
    _fields_ = [(name, c.c_ubyte) for name in (
        'PowerButtonPresent', 'SleepButtonPresent', 'LidPresent',
        'SystemS1', 'SystemS2', 'SystemS3', 'SystemS4', 'SystemS5',
        'HiberFilePresent', 'FullWake', 'VideoDimPresent', 'ApmPresent',
        'UpsPresent', 'ThermalControl', 'ProcessorThrottle', 'ProcessorMinThrottle',
        'ProcessorMaxThrottle', 'FastSystemS4', 'Hiberboot', 'WakeAlarmPresent',
        'AoAc', 'DiskSpinDown', 'HiberFileType', 'AoAcConnectivitySupported')]
    _fields_ += [('spare', c.c_ubyte * 6), ('SystemBatteriesPresent', c.c_ubyte),
                 ('BatteriesAreShortTerm', c.c_ubyte), ('BatteryScale', _BatteryScale * 3)]
    _fields_ += [(name, w.DWORD) for name in (
        'AcOnLineWake', 'SoftLidWake', 'RtcWake', 'MinDeviceWakeState', 'DefaultLowLatencyWake')]


def validate(value):
    if (not isinstance(value, dict) or set(value) != {'hibernate'} or
            type(value['hibernate']) is not bool):
        raise ValueError('Invalid Windows power capabilities')
    return dict(value)


def _api():
    if os.name != 'nt':
        raise RuntimeError('Windows power management requires Windows')
    api = c.WinDLL('powrprof.dll', winmode=0x800, use_last_error=True)
    api.GetPwrCapabilities.argtypes, api.GetPwrCapabilities.restype = [c.POINTER(_Capabilities)], c.c_ubyte
    api.SetSuspendState.argtypes, api.SetSuspendState.restype = [c.c_ubyte] * 3, c.c_ubyte
    return api


def capabilities():
    if os.name != 'nt':
        return {'hibernate': False}
    value = _Capabilities()
    if not _api().GetPwrCapabilities(c.byref(value)):
        raise c.WinError(c.get_last_error())
    return {'hibernate': bool(value.SystemS4 and value.HiberFilePresent and value.HiberFileType == 2)}


@contextmanager
def _shutdown_privilege():
    class Luid(c.Structure):
        _fields_ = [('low', w.DWORD), ('high', w.LONG)]
    class Privilege(c.Structure):
        _fields_ = [('count', w.DWORD), ('luid', Luid), ('attributes', w.DWORD)]
    kernel = c.WinDLL('kernel32.dll', winmode=0x800, use_last_error=True)
    security = c.WinDLL('advapi32.dll', winmode=0x800, use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    security.OpenProcessToken.argtypes, security.OpenProcessToken.restype = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)], w.BOOL
    security.LookupPrivilegeValueW.argtypes, security.LookupPrivilegeValueW.restype = [w.LPCWSTR, w.LPCWSTR, c.POINTER(Luid)], w.BOOL
    security.AdjustTokenPrivileges.argtypes = [w.HANDLE, w.BOOL, c.POINTER(Privilege), w.DWORD, c.c_void_p, c.c_void_p]
    security.AdjustTokenPrivileges.restype = w.BOOL
    token, privilege = w.HANDLE(), Privilege()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x28, c.byref(token)):
        raise c.WinError(c.get_last_error())
    try:
        privilege.count, privilege.attributes = 1, 2
        if not security.LookupPrivilegeValueW(None, 'SeShutdownPrivilege', c.byref(privilege.luid)):
            raise c.WinError(c.get_last_error())
        c.set_last_error(0)
        if not security.AdjustTokenPrivileges(token, False, c.byref(privilege), 0, None, None):
            raise c.WinError(c.get_last_error())
        if c.get_last_error():
            raise c.WinError(c.get_last_error())
        yield
    finally:
        kernel.CloseHandle(token)


def hibernate():
    if not capabilities()['hibernate']:
        raise ValueError('Hibernation is not enabled on this system')
    with _shutdown_privilege():
        # No forced shutdown or disabled wake events. Only this confirmed action
        # enters S4; displaying the menu never changes the power configuration.
        if not _api().SetSuspendState(True, False, False):
            raise c.WinError(c.get_last_error())
    return True


def shutdown(restart):
    with _shutdown_privilege():
        user = c.WinDLL('user32.dll', winmode=0x800, use_last_error=True)
        user.ExitWindowsEx.argtypes, user.ExitWindowsEx.restype = [w.UINT, w.DWORD], w.BOOL
        if not user.ExitWindowsEx(2 if restart else 8, 0x80040000):
            raise c.WinError(c.get_last_error())
    return True
