# SPDX-License-Identifier: GPL-2.0-or-later
"""Worker-thread deadline clock excluding time Windows is asleep/hibernating."""
import ctypes as c


def active_clock():
    # Called only in the job thread, never menu draw or job admission. Keeping a
    # bounded *awake* deadline avoids killing the hibernate helper on resume.
    kernel = c.WinDLL('kernel32.dll', winmode=0x800, use_last_error=True)
    query = kernel.QueryUnbiasedInterruptTime
    query.argtypes, query.restype = [c.POINTER(c.c_ulonglong)], c.c_int

    def now():
        value = c.c_ulonglong()
        if not query(c.byref(value)):
            raise OSError('Unable to read the Windows awake-time clock')
        return value.value / 10_000_000

    now()  # Fail before launching a power action if this clock is unavailable.
    return now
