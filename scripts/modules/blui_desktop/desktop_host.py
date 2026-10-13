# SPDX-License-Identifier: GPL-2.0-or-later
"""Main-thread facade: bounded RAM only. All OS/filesystem/pipe I/O is in workers."""
import atexit
from collections import deque
import json
import os
import subprocess
import threading
import time

from .desktop_host_state import surfaces

_controller = None
_default = {'enabled': False, 'attached_count': 0, 'pending_restore': False,
            'need_rebind': False, 'handles': [], 'state': 'Windows Desktop Unchanged', 'error': '',
            'completed_serial': 0}


def status(value):
    if (not isinstance(value, dict) or set(value) != set(_default) or
            any(type(value[field]) is not bool for field in ('enabled', 'pending_restore', 'need_rebind')) or
            type(value['attached_count']) is not int or not 0 <= value['attached_count'] <= 32 or
            type(value['completed_serial']) is not int or not 0 <= value['completed_serial'] < 1 << 53 or
            not isinstance(value['handles'], list) or len(value['handles']) != value['attached_count'] or
            any(not isinstance(handle, str) or not handle.isdigit() or len(handle) > 20 or
                not 0 < int(handle) < 1 << 64 for handle in value['handles']) or
            len(set(value['handles'])) != len(value['handles']) or
            any(not isinstance(value[field], str) or len(value[field]) > 2048 or '\x00' in value[field]
                for field in ('state', 'error'))):
        raise ValueError('Invalid desktop host status')
    return dict(value, handles=list(value['handles']))


class Controller:
    def __init__(self, directory):
        if not isinstance(directory, str) or not os.path.isabs(directory) or '\x00' in directory:
            raise ValueError('Invalid desktop recovery directory')
        self.directory = directory
        self._lock = threading.Lock()
        self._commands = deque(maxlen=32)
        self._wake, self._stopping = threading.Event(), threading.Event()
        self._ui_seen = time.monotonic()
        self._state = dict(_default, handles=[])
        self._serial = 0
        self.process = None
        self._thread = threading.Thread(target=self._run, name='BLUI desktop host control', daemon=True)
        self._thread.start()

    def request(self, kind, rows=None):
        if kind not in ('reconcile', 'restore'):
            raise ValueError('Unsupported desktop host request')
        value = {'command': kind}
        if kind == 'reconcile':
            value['surfaces'] = surfaces(rows)
        with self._lock:
            if self._stopping.is_set():
                raise RuntimeError('The desktop host is shutting down')
            self._serial += 1
            if self._serial >= 1 << 53:
                raise RuntimeError('Desktop host command serial exhausted')
            value['serial'] = self._serial
            # Only the newest topology is useful. Do not silently drop restore.
            self._commands.clear()
            self._commands.append(value)
            self._ui_seen = time.monotonic()
        self._wake.set()
        return value['serial']

    def tick(self):
        with self._lock:
            self._ui_seen = time.monotonic()
            return dict(self._state, handles=list(self._state['handles']))

    def snapshot(self):
        with self._lock:
            return dict(self._state, handles=list(self._state['handles']))

    def close(self):
        self._stopping.set()
        self._wake.set()

    def _read(self, process):
        try:
            while True:
                line = process.stdout.readline(8193)
                if not line:
                    break
                if len(line) > 8192 or not line.endswith(b'\n'):
                    raise ValueError('Desktop host response is too large')
                value = status(json.loads(line.decode('utf-8')))
                with self._lock:
                    self._state = value
        except (OSError, ValueError, UnicodeError) as exc:
            with self._lock:
                self._state = dict(_default, handles=[], state='Desktop Host Unavailable', error=str(exc)[:2048])
            self.close()  # EOF makes both independent guardians restore, not leave icons hidden.

    def _run(self):
        process = reader = None
        try:
            if os.name != 'nt':
                raise RuntimeError('Desktop replacement is available only on Windows')
            from blui_explorer.shell_client import python_executable
            from .native_windows import _process_start
            started = _process_start(os.getpid())
            if not started:
                raise RuntimeError('Unable to verify the BLUI desktop owner')
            process = subprocess.Popen([python_executable(), '-I', '-B', '-u', '-X', 'utf8',
                os.path.join(os.path.dirname(__file__), 'desktop_host_watchdog.py'), self.directory,
                str(os.getpid()), started], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.process = process
            reader = threading.Thread(target=self._read, args=(process,), daemon=True,
                                      name='BLUI desktop host status')
            reader.start()
            heartbeat = 0
            while process.poll() is None:
                with self._lock:
                    commands = list(self._commands)
                    self._commands.clear()
                    ui_seen = self._ui_seen
                now = time.monotonic()
                if self._stopping.is_set():
                    commands = [{'command': 'shutdown'}]
                elif now >= heartbeat and now - ui_seen < 5:
                    commands.append({'command': 'heartbeat'})
                    heartbeat = now + 2
                for value in commands:
                    process.stdin.write(json.dumps(value, ensure_ascii=False).encode('utf-8') + b'\n')
                    process.stdin.flush()
                if self._stopping.is_set():
                    break
                self._wake.wait(.1)
                self._wake.clear()
        except (OSError, ValueError, RuntimeError) as exc:
            with self._lock:
                self._state = dict(_default, handles=[], state='Desktop Host Unavailable', error=str(exc)[:2048])
        finally:
            if process:
                try:
                    process.stdin.close()
                    process.wait(timeout=3)
                    if reader:
                        reader.join(timeout=.2)
                    if not reader or not reader.is_alive():
                        process.stdout.close()
                except (OSError, subprocess.TimeoutExpired):
                    pass  # Never kill a service that may still be restoring the desktop.
            with self._lock:
                if self._state['enabled'] or self._state['pending_restore']:
                    self._state = dict(_default, handles=[], pending_restore=True,
                                       state='Desktop Recovery Pending',
                                       error='Desktop host exited; use Restore Windows Desktop')
            self._stopping.set()


def start(directory):
    global _controller
    if _controller is None or _controller._stopping.is_set():
        _controller = Controller(directory)
    return _controller


def reconcile(rows):
    if _controller is None:
        raise RuntimeError('The desktop host has not started')
    return _controller.request('reconcile', rows)


def restore():
    if _controller is not None:
        controller = start(_controller.directory) if _controller._stopping.is_set() else _controller
        return controller.request('restore')
    return 0


def tick():
    return _controller.tick() if _controller else dict(_default, handles=[])


def snapshot():
    return _controller.snapshot() if _controller else dict(_default, handles=[])


def close():
    if _controller:
        _controller.close()


atexit.register(close)
