# SPDX-License-Identifier: GPL-2.0-or-later
"""Nonblocking UI facade; all OS/filesystem work runs outside Blender's main thread."""
# Design reference, not copied implementation:
# https://github.com/dremin/RetroBar (Apache-2.0, WPF + ManagedShell)
# https://github.com/cairoshell/ManagedShell/blob/master/src/ManagedShell.AppBar/ExplorerHelper.cs
# BLUI deliberately preserves system AppBar/autohide/workarea settings; its native
# independent native taskbar is not a notification-area host or registered shell AppBar.
import atexit
from collections import deque
import json
import os
import subprocess
import threading
import time

_controller = None
_default = {'enabled': False, 'hidden_count': 0, 'state': 'Windows Taskbar Unchanged',
            'error': '', 'tasks_revision': 0, 'events_available': False}


class Controller:
    def __init__(self, directory):
        if not isinstance(directory, str) or not os.path.isabs(directory) or '\x00' in directory:
            raise ValueError('Invalid taskbar recovery directory')
        self.directory = directory
        self._lock = threading.Lock()
        self._commands = deque(maxlen=32)
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._state = dict(_default)
        self._ui_seen = time.monotonic()
        self.process = None
        self._thread = threading.Thread(target=self._run, name='BLUI taskbar guard', daemon=True)
        self._thread.start()

    def request(self, command):
        if command not in ('hide', 'restore'):
            raise ValueError('Unsupported Windows taskbar command')
        with self._lock:
            if self._stopping.is_set():
                raise RuntimeError('The taskbar guard is shutting down')
            self._commands.append(command)
            self._ui_seen = time.monotonic()
        self._wake.set()

    def tick(self):
        with self._lock:
            self._ui_seen = time.monotonic()
            return dict(self._state)

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def close(self):
        # No process wait/kill, filesystem access or Win32 API on the UI thread.
        self._stopping.set()
        self._wake.set()

    def _status_reader(self, process):
        try:
            while True:
                line = process.stdout.readline(8193)
                if not line:
                    break
                if len(line) > 8192 or not line.endswith(b'\n'):
                    raise ValueError('Invalid taskbar service response')
                value = json.loads(line)
                if (not isinstance(value, dict) or type(value.get('enabled')) is not bool or
                        type(value.get('hidden_count')) is not int or not 0 <= value['hidden_count'] <= 32 or
                        type(value.get('tasks_revision')) is not int or not 0 <= value['tasks_revision'] < 1 << 63 or
                        type(value.get('events_available')) is not bool or
                        any(not isinstance(value.get(field), str) or len(value[field]) > 2048
                            for field in ('state', 'error'))):
                    raise ValueError('Invalid taskbar service response')
                with self._lock:
                    self._state = value
        except (OSError, ValueError) as exc:
            with self._lock:
                self._state = dict(_default, state='Taskbar Service Unavailable', error=str(exc))

    def _run(self):
        process = None
        try:
            if os.name != 'nt':
                raise RuntimeError('Windows taskbar control is only available on Windows')
            from blui_explorer.shell_client import python_executable
            from .native_windows import _process_start
            started = _process_start(os.getpid())
            if not started:
                raise RuntimeError('Unable to verify the BLUI taskbar owner')
            process = subprocess.Popen([python_executable(), '-I', '-B', '-u',
                os.path.join(os.path.dirname(__file__), 'taskbar_watchdog.py'), self.directory,
                str(os.getpid()), started], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.process = process
            reader = threading.Thread(target=self._status_reader, args=(process,), daemon=True,
                                      name='BLUI taskbar status')
            reader.start()
            next_heartbeat = 0
            while process.poll() is None:
                with self._lock:
                    commands = list(self._commands)
                    self._commands.clear()
                    ui_seen = self._ui_seen
                now = time.monotonic()
                if self._stopping.is_set():
                    commands = ['shutdown']
                elif now >= next_heartbeat and now - ui_seen < 5:
                    commands.append('heartbeat')
                    next_heartbeat = now + 2
                for command in commands:
                    process.stdin.write((json.dumps(command) + '\n').encode('utf-8'))
                    process.stdin.flush()
                if self._stopping.is_set():
                    break
                self._wake.wait(.1)
                self._wake.clear()
        except (OSError, ValueError, RuntimeError) as exc:
            with self._lock:
                self._state = dict(_default, state='Taskbar Service Unavailable', error=str(exc))
        finally:
            if process:
                try:
                    process.stdin.close()  # EOF also requests restoration.
                    process.wait(timeout=3)
                    reader.join(timeout=.2)
                    if not reader.is_alive():
                        process.stdout.close()
                except (OSError, subprocess.TimeoutExpired):
                    # NEVER kill a guard that may still be restoring shellbars.
                    pass
            with self._lock:
                if self._state.get('enabled') or self._state.get('hidden_count'):
                    self._state = dict(_default, state='Taskbar Recovery Pending',
                                       error='Taskbar guard exited; use Restore Windows Taskbar')
                elif not self._state.get('error'):
                    self._state = dict(_default, state='Windows Taskbar Restored')
            self._stopping.set()


def start(directory):
    global _controller
    if _controller is None or _controller._stopping.is_set():
        _controller = Controller(directory)
    return _controller


def request(command):
    if _controller is None:
        raise RuntimeError('The desktop taskbar guard has not started')
    _controller.request(command)


def tick():
    return _controller.tick() if _controller else dict(_default)


def snapshot():
    return _controller.snapshot() if _controller else dict(_default)


def close():
    if _controller:
        _controller.close()


atexit.register(close)
