# SPDX-License-Identifier: GPL-2.0-or-later
"""Nonblocking desktop jobs; timeout kills only the subprocess created for this job."""
import atexit
import base64
from copy import deepcopy
import math
import os
import shutil
import subprocess
import tempfile
import time
import threading
from blui_explorer import mailbox
from blui_explorer.shell_client import python_executable
from . import background, boards, model, monitors, icons, weather

_live = set()
_live_lock = threading.Lock()


def _validate_rows(rows):
    if not isinstance(rows, list) or len(rows) > model.LIMIT:
        raise ValueError('Invalid desktop entries')
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('folder')) is not bool or
            any(not isinstance(row.get(field), str) or len(row[field]) > 32768 or
                '\x00' in row[field] for field in ('path', 'name'))):
            raise ValueError('Invalid desktop entry')


def _validate_value(action, value):
    if action == 'scan':
        if not isinstance(value, dict) or type(value.get('truncated')) is not bool:
            raise ValueError('Invalid desktop scan')
        _validate_rows(value.get('rows'))
    elif action == 'paths':
        _validate_rows(value)
    elif action == 'load':
        model.validate(value)
    elif action == 'save':
        if not isinstance(value, str) or len(value) > 32768 or '\x00' in value:
            raise ValueError('Invalid desktop save result')
    elif action in {'open', 'recycle'}:
        if value is not True:
            raise ValueError('Invalid desktop open result')
    elif action == 'background':
        background.validate_pixels(value)
    elif action == 'board_load':
        boards.validate(value)
    elif action == 'board_save':
        if (not isinstance(value, dict) or not boards.uuid_key(value.get('id')) or
                type(value.get('revision')) is not int or not 0 <= value['revision'] <= boards.MAX_REVISION or
                not isinstance(value.get('path'), str) or not value['path'] or
                len(value['path']) > 32768 or '\x00' in value['path']):
            raise ValueError('Invalid desktop autosave result')
    elif action == 'monitors':
        monitors.validate(value)
    elif action == 'weather':
        if (not isinstance(value, dict) or any(type(value.get(key)) is not bool for key in ('cached', 'stale')) or
                not isinstance(value.get('error'), str) or len(value['error']) > 1024):
            raise ValueError('Invalid desktop weather result')
        data = value.get('data')
        if data is not None:
            if not isinstance(data, dict):
                raise ValueError('Invalid desktop weather data')
            weather._validate_cache(data, data.get('latitude'), data.get('longitude'), data.get('source'))
    elif action == 'icons':
        if not isinstance(value, list) or len(value) > icons.BATCH or any(
                not isinstance(row, dict) for row in value):
            raise ValueError('Invalid desktop icon result')
        for row in value:
            if (not isinstance(row.get('path'), str) or len(row['path']) > 32768 or '\x00' in row['path'] or
                any(type(row.get(key)) is not int or not 0 <= row[key] <= 1024 for key in ('width', 'height')) or
                not isinstance(row.get('rgba'), str) or len(row['rgba']) > 5592408 or
                len(base64.b64decode(row['rgba'], validate=True)) != row['width'] * row['height'] * 4):
                raise ValueError('Invalid desktop icon pixels')
    elif action == 'tasks':
        if not isinstance(value, list) or len(value) > 256:
            raise ValueError('Invalid desktop tasks')
        for row in value:
            if (not isinstance(row, dict) or
                any(type(row.get(field)) is not bool for field in ('active', 'minimized', 'actionable')) or
                any(not isinstance(row.get(field), str) or len(row[field]) > 32768 or '\x00' in row[field]
                    for field in ('handle', 'title', 'process_started', 'window_class')) or
                any(type(row.get(field)) is not int or not 0 < row[field] <= 0xffffffff
                    for field in ('pid', 'thread_id'))):
                raise ValueError('Invalid desktop task identity')


class Job:
    def __init__(self, action, *args, timeout=10.0):
        arity = {'scan': 1, 'paths': 1, 'save': 2, 'load': 1, 'tasks': 0, 'open': 1,
                 'board_save': 2, 'board_load': 1, 'monitors': 0, 'weather': 1, 'icons': 1,
                 'background': 1, 'recycle': 1}
        if not isinstance(action, str) or action not in arity or len(args) != arity[action]:
            raise ValueError('Unsupported desktop request')
        if action == 'open' and (os.name != 'nt' or not isinstance(args[0], str) or
                                 not args[0] or len(args[0]) > 32768 or '\x00' in args[0]):
            raise ValueError('Invalid desktop open path')
        if type(timeout) not in (int, float) or not 0 < timeout <= 60 or not math.isfinite(timeout):
            raise ValueError('Invalid desktop timeout')
        if action == 'weather' and not isinstance(args[0], dict):
            raise ValueError('Invalid desktop weather request')
        if action == 'recycle' and (not isinstance(args[0], list) or not 0 < len(args[0]) <= model.LIMIT or
                any(not isinstance(path, str) or not path or len(path) > 32768 or '\x00' in path for path in args[0])):
            raise ValueError('Invalid recycle request')
        if action == 'icons' and (not isinstance(args[0], (list, tuple)) or len(args[0]) > icons.BATCH or
                any(not isinstance(path, str) or not path or len(path) > 32768 or '\x00' in path for path in args[0])):
            raise ValueError('Invalid desktop icon paths')
        self.directory = ''
        self.process = None
        self.started, self.timeout = time.monotonic(), timeout
        self.reply = None
        self.action = action
        self.closed = False
        self.exited = None
        self._cancel = threading.Event()
        self._finished = threading.Event()
        self._cleaned = threading.Event()
        self._prepared = threading.Event()
        self._state_lock = threading.Lock()
        self._request = {'action': action, 'args': deepcopy(list(args))}
        # Admission remains reserved until the private helper has actually exited,
        # even when users repeatedly cancel/create requests.
        with _live_lock:
            if len(_live) >= 8:
                raise RuntimeError('Desktop service is busy; try again shortly')
            _live.add(self)
        try:
            self._thread = threading.Thread(target=self._run, name='BLUI desktop service', daemon=True)
            self._thread.start()
        except Exception:
            with _live_lock:
                _live.discard(self)
            self._cleaned.set()
            raise

    def done(self):
        return self._finished.is_set()

    def _finish(self, reply):
        with self._state_lock:
            if self._finished.is_set():
                return
            self.reply = {'ok': False, 'error': 'Desktop job was cancelled'} if self._cancel.is_set() else reply
            self._finished.set()

    def _run(self):
        """All filesystem access and process work is confined to this bounded thread."""
        try:
            if self._cancel.is_set():
                return
            self.directory = tempfile.mkdtemp(prefix='blui_desktop_job_')
            if self._cancel.is_set():
                return
            mailbox.publish(self.directory, 'request.json', self._request)
            if self._cancel.is_set():
                return
            self.process = subprocess.Popen([python_executable(), '-I', '-B', '-u',
                os.path.join(os.path.dirname(__file__), 'worker.py'), self.directory],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._prepared.set()
            # Popen itself may have blocked while cancellation was delivered.
            # This exact owned process is cleaned in finally, never leaked or reused.
            while not self._cancel.is_set():
                result_file = os.path.join(self.directory, 'result.json')
                try:
                    size = os.stat(result_file).st_size
                except (FileNotFoundError, PermissionError):
                    size = 0
                if size > model.MAX_BYTES:
                    raise ValueError('Desktop response is too large')
                reply = mailbox.take(self.directory, 'result.json')
                if reply is not None:
                    if (not isinstance(reply, dict) or type(reply.get('ok')) is not bool or
                        ('value' not in reply if reply['ok'] else not isinstance(reply.get('error'), str))):
                        raise ValueError('Invalid desktop response')
                    if reply['ok']:
                        _validate_value(self.action, reply['value'])
                    self._finish(reply)
                    return
                if time.monotonic() - self.started > self.timeout:
                    self._finish({'ok': False, 'error': 'Desktop service timed out; the UI is still available'})
                    return
                if self.process.poll() is not None:
                    # A scanner may briefly hold a final result after the child exits.
                    if self.exited is None:
                        self.exited = time.monotonic()
                    elif time.monotonic() - self.exited >= .5:
                        self._finish({'ok': False, 'error': 'Desktop service exited unexpectedly'})
                        return
                self._cancel.wait(.02)
        except Exception as exc:
            self._finish({'ok': False, 'error': 'Invalid desktop response: ' + str(exc)})
        finally:
            self._prepared.set()
            self._finish({'ok': False, 'error': 'Desktop job was cancelled'})
            process = self.process
            if process:
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=.2)
                except (subprocess.TimeoutExpired, OSError):
                    pass
            if self.directory:
                shutil.rmtree(self.directory, ignore_errors=True)
            with _live_lock:
                _live.discard(self)
            self._cleaned.set()

    def result(self):
        try:
            if not self.reply or not self.reply['ok']:
                raise RuntimeError(self.reply['error'] if self.reply else 'Desktop result unavailable')
            return self.reply['value']
        finally:
            self.close()

    def close(self):
        # Called by UI timers/undo/load/exit. No kill, wait, stat, unlink or join here.
        with self._state_lock:
            if self.closed:
                return
            self.closed = True
            if not self._finished.is_set():
                self._cancel.set()
                self.reply = {'ok': False, 'error': 'Desktop job was cancelled'}
                self._finished.set()


def close_all():
    with _live_lock:
        jobs = list(_live)
    for job in jobs:
        job.close()


atexit.register(close_all)
