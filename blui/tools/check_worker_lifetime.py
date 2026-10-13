# SPDX-License-Identifier: GPL-2.0-or-later
"""Real parent-exit ownership check; only processes created by this fixture are ended."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))


if len(sys.argv) > 1 and sys.argv[1] == 'helper':
    from blui_explorer import worker_lifetime
    assert worker_lifetime.start()
    Path(sys.argv[2]).write_text(str(os.getpid()), encoding='utf-8')
    while True:
        time.sleep(.1)
elif len(sys.argv) > 1 and sys.argv[1] == 'parent':
    child = subprocess.Popen([sys.executable, '-I', '-B', __file__, 'helper', sys.argv[2]],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    while not Path(sys.argv[2]).is_file():
        if child.poll() is not None:
            raise RuntimeError('Owned helper did not start')
        time.sleep(.01)
    # Abruptly exit the parent, like a crash, without child cleanup.
    os._exit(0)
else:
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    with tempfile.TemporaryDirectory(prefix='blui_lifetime_qa_') as folder:
        marker = Path(folder) / 'pid.txt'
        parent = subprocess.Popen([sys.executable, '-I', '-B', __file__, 'parent', str(marker)],
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        parent.wait(timeout=5)
        pid = int(marker.read_text(encoding='utf-8'))
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 3000) == 0, 'Owned helper survived original parent'
            finally:
                kernel.CloseHandle(handle)
        print('check_worker_lifetime: PASS (real abrupt parent exit ends only its helper)', flush=True)
