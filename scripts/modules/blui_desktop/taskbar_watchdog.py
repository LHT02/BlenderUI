# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent helper: restore owned shellbars on owner death, EOF or UI heartbeat loss."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
import queue
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blui_desktop.taskbar_native import OwnerProcess, SessionLock, WindowsBars
from blui_desktop.taskbar_state import Guard, Journal
from blui_desktop.native_windows import _process_start


class TaskEvents:
    """Out-of-context WinEvent hooks: no DLL injection, callback only marks dirty."""
    def __init__(self):
        self.user = c.WinDLL('user32', use_last_error=True)
        prototype = c.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND,
                                 w.LONG, w.LONG, w.DWORD, w.DWORD)
        self.dirty = True
        self.revision = 1
        def event(_hook, event_id, _hwnd, object_id, child_id, _thread, _time):
            if event_id < 0x8000 or (object_id == 0 and child_id == 0):
                self.dirty = True
        self.callback = prototype(event)
        self.user.SetWinEventHook.argtypes = [w.DWORD, w.DWORD, w.HANDLE, prototype,
                                           w.DWORD, w.DWORD, w.DWORD]
        self.user.SetWinEventHook.restype = w.HANDLE
        self.user.UnhookWinEvent.argtypes, self.user.UnhookWinEvent.restype = [w.HANDLE], w.BOOL
        self.user.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        self.user.PeekMessageW.restype = w.BOOL
        self.user.TranslateMessage.argtypes, self.user.TranslateMessage.restype = [c.POINTER(w.MSG)], w.BOOL
        self.user.DispatchMessageW.argtypes, self.user.DispatchMessageW.restype = [c.POINTER(w.MSG)], c.c_ssize_t
        self.hooks = [self.user.SetWinEventHook(first, last, None, self.callback, 0, 0, 2)
                      for first, last in ((3, 3), (0x16, 0x17), (0x8000, 0x800C))]
        self.last_revision = 0.0

    def pump(self, now):
        msg = w.MSG()
        for _ in range(256):
            if not self.user.PeekMessageW(c.byref(msg), None, 0, 0, 1):
                break
            self.user.TranslateMessage(c.byref(msg))
            self.user.DispatchMessageW(c.byref(msg))
        if self.dirty and now - self.last_revision >= .2:
            self.revision += 1
            self.last_revision = now
            self.dirty = False

    def close(self):
        for handle in self.hooks:
            if handle:
                self.user.UnhookWinEvent(handle)
        self.hooks.clear()


def run(directory, pid, started):
    lock = owner = events = guard = None
    failure = ''
    inbox = queue.Queue(maxsize=32)
    eof = threading.Event()
    def reader():
        try:
            while True:
                line = sys.stdin.buffer.readline(4097)
                if not line:
                    break
                if len(line) > 4096 or not line.endswith(b'\n'):
                    break
                try:
                    command = json.loads(line)
                    if command in ('heartbeat', 'hide', 'restore', 'shutdown'):
                        inbox.put_nowait(command)
                except (ValueError, TypeError, queue.Full):
                    pass
        finally:
            eof.set()
    def emit(value):
        sys.stdout.write(json.dumps(value, ensure_ascii=False) + '\n')
        sys.stdout.flush()
    try:
        lock = SessionLock()
        owner = OwnerProcess(pid, started)
        guard = Guard(WindowsBars(), Journal(directory))
        guard.restore()  # Recover only identities recorded by a previous BLUI guard.
        # Start a second minimal process BEFORE any future hide. It retains kernel
        # identities for both BLUI and this helper; it cannot accidentally follow
        # a recycled PID. Neither helper imports bpy or runs in Blender's UI loop.
        recovery = subprocess.Popen([sys.executable, '-I', '-B', '-u',
            os.path.join(os.path.dirname(__file__), 'taskbar_recovery.py'), directory,
            str(pid), started, str(os.getpid()), _process_start(os.getpid())],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ready = queue.Queue(maxsize=1)
        def read_ready():
            try:
                ready.put_nowait(recovery.stdout.readline(32))
            except (OSError, queue.Full):
                pass
        threading.Thread(target=read_ready, daemon=True).start()
        try:
            acknowledged = ready.get(timeout=5)
        except queue.Empty:
            acknowledged = b''
        if acknowledged.strip() != b'READY' or recovery.poll() is not None:
            raise RuntimeError('The independent taskbar recovery guard is unavailable')
        recovery.stdout.close()
        events = TaskEvents()
        threading.Thread(target=reader, name='BLUI taskbar commands', daemon=True).start()
        heartbeat = refresh = status_at = time.monotonic()
        previous_status = None
        while owner.alive() and not eof.is_set():
            if recovery.poll() is not None:
                raise RuntimeError('The independent taskbar recovery guard exited')
            now = time.monotonic()
            events.pump(now)
            try:
                command = inbox.get(timeout=.05)
            except queue.Empty:
                command = None
            if command == 'heartbeat':
                heartbeat = now
            elif command == 'hide':
                heartbeat = now
                guard.hide()
            elif command == 'restore':
                guard.restore()
            elif command == 'shutdown':
                break
            if now - heartbeat > 15:
                # A hung UI must not leave Windows without a usable taskbar.
                guard.restore()
            if now - refresh >= .25:
                guard.refresh()
                refresh = now
            status = guard.status()
            status['tasks_revision'] = events.revision
            status['events_available'] = all(events.hooks)
            if status != previous_status or now - status_at >= 2:
                emit(status)
                previous_status, status_at = status, now
    except Exception as exc:
        failure = str(exc)[:2048]
        try:
            emit({'enabled': False, 'hidden_count': 0, 'state': 'Taskbar Service Unavailable',
                  'error': failure, 'tasks_revision': 0, 'events_available': False})
        except (BrokenPipeError, OSError):
            pass
    finally:
        if events:
            events.close()
        if guard:
            # ShowWindowAsync can take a message-loop turn. Retry briefly without
            # blocking BLUI; unresolved identities remain in the durable journal.
            for _ in range(10):
                try:
                    if guard.restore():
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(.1)
            try:
                final_status = guard.status()
                final_status.update(tasks_revision=0, events_available=False)
                if failure:
                    final_status['error'] = failure
                if final_status['hidden_count']:
                    final_status['error'] = 'Taskbar recovery is pending; use Restore Windows Taskbar'
                emit(final_status)
            except (BrokenPipeError, OSError, ValueError):
                pass
        if owner:
            owner.close()
        if lock:
            lock.close()


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit(2)
    run(sys.argv[1], int(sys.argv[2]), sys.argv[3])
