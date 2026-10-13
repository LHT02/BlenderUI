# SPDX-License-Identifier: GPL-2.0-or-later
"""Nonblocking notification host ownership; pipe/process I/O never runs in the UI.

Only poll creates Blender previews, in batches of eight. Draw/command callbacks
read RAM or append a bounded command; the helper rechecks every native identity.
"""
import atexit
import copy
import json
import os
import queue
import subprocess
import sys
import threading
import time
from . import notification_wire as wire

_owner = None
_retired = []
_state = wire.empty()
_pixels = {}
_pending = {}
_retry_at = 0.0


class _Owner:
    def __init__(self, private):
        self.commands = queue.Queue(maxsize=wire.MAX_COMMANDS)
        self.updates = queue.Queue(maxsize=2)
        self.stopping = threading.Event()
        self.finished = threading.Event()
        self.last_received = time.monotonic()
        self.error = ''
        self.helper_pid = 0  # Immutable creation identity for owned diagnostic fixtures.
        self.thread = threading.Thread(target=self._run, args=(private,), daemon=True,
                                       name='BLUI notification client')
        self.thread.start()

    def publish(self, value):
        try:
            self.updates.put_nowait(value)
        except queue.Full:
            try:
                self.updates.get_nowait()
                self.updates.put_nowait(value)
            except (queue.Empty, queue.Full):
                pass

    def _read(self, process):
        try:
            while not self.stopping.is_set():
                line = process.stdout.readline(wire.MAX_BYTES + 1)
                if not line:
                    break
                if len(line) > wire.MAX_BYTES or not line.endswith(b'\n'):
                    raise ValueError('Notification snapshot is too large or incomplete')
                value, pixels = wire.validate_snapshot(json.loads(line.decode('utf-8')))
                if value['error']:
                    self.error = value['error']
                self.last_received = time.monotonic()
                self.publish((value, pixels))
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            self.error = str(exc)
            self.publish((wire.empty(str(exc)), {}))
        finally:
            self.stopping.set()
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass

    @staticmethod
    def _write(process, value):
        data = (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
        if len(data) > 8192:
            raise ValueError('Notification command is too large')
        process.stdin.write(data)
        process.stdin.flush()

    def _write_loop(self, process):
        # A stalled native receiver can fill its input pipe. Keep that blocking
        # write separate from the supervisor, which must still be able to stop it.
        try:
            while True:
                try:
                    value = self.commands.get(timeout=.2)
                except queue.Empty:
                    if self.stopping.is_set():
                        break
                    continue
                self._write(process, value)
                if value['command'] == 'shutdown':
                    break
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self.stopping.set()
        finally:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass

    def _run(self, private):
        process = None
        try:
            from blui_explorer.shell_client import python_executable
            from . import native_windows
            arguments = [python_executable(), '-I', '-B', '-u', '-X', 'utf8',
                         os.path.join(os.path.dirname(__file__), 'notification_host.py'),
                         str(os.getpid()), native_windows._process_start(os.getpid())]
            if private:
                arguments.append('--qa-private')
            if self.stopping.is_set():
                return
            process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.helper_pid = process.pid
            threading.Thread(target=self._read, args=(process,), daemon=True,
                             name='BLUI notification replies').start()
            threading.Thread(target=self._write_loop, args=(process,), daemon=True,
                             name='BLUI notification requests').start()
            while not self.stopping.is_set() and process.poll() is None:
                self.stopping.wait(.1)
        except (OSError, ValueError, RuntimeError) as exc:
            self.error = str(exc)
            self.publish((wire.empty(str(exc)), {}))
        finally:
            # Only this Popen instance is ever signalled. Close asynchronously,
            # giving the host its chance to destroy itself and restore broadcasts.
            if process is not None:
                try:
                    self.stopping.set()
                    while not self.commands.empty():
                        try:
                            self.commands.get_nowait()
                        except queue.Empty:
                            break
                    self.commands.put_nowait({'command': 'shutdown'})
                    process.wait(timeout=2)
                except (OSError, ValueError, queue.Full, subprocess.TimeoutExpired):
                    if process.poll() is None:
                        process.kill()
                        try:
                            process.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            pass
            self.publish((wire.empty(self.error or 'Notification area host exited'), {}))
            self.finished.set()

    def close(self):
        self.stopping.set()


def start():
    """Idempotent explicit host request; QA can only opt into its private receiver."""
    global _owner, _retry_at, _state
    if _owner is not None:
        return not _owner.finished.is_set()
    _retired[:] = [owner for owner in _retired if not owner.finished.is_set()]
    if _retired or time.monotonic() < _retry_at or os.name != 'nt':
        return False
    from . import session
    private = os.environ.get('BLUI_NOTIFY_QA_PRIVATE') == '1'
    if session.disable_for_tests and not private:
        return False
    _owner = _Owner(private)
    _state = wire.empty()
    _retry_at = time.monotonic() + 10
    return True


def poll():
    """Consume validated RAM mailboxes and create a bounded batch of previews."""
    global _state, _pixels, _owner
    changed = False
    if _owner is None:
        return False
    while True:
        try:
            value, pixels = _owner.updates.get_nowait()
        except queue.Empty:
            break
        _state, _pixels = value, pixels
        changed = True
    if (_state['enabled'] and time.monotonic() - _owner.last_received > 6) or _owner.finished.is_set():
        _state, _pixels = wire.empty(_state['error'] or 'Notification area is unavailable'), {}
        _owner.close()
        if _owner.finished.is_set():
            _owner = None
        changed = True
    from . import icon_cache
    wanted = set(_pixels)
    for key in list(_pending):
        if key not in wanted:
            _pending.pop(key, None)
    for key, row in _pixels.items():
        if not icon_cache.cached_value(key):
            _pending[key] = row
    batch = list(_pending.values())[:8]
    if batch:
        icon_cache.apply(batch)
        for row in batch:
            _pending.pop(row['path'], None)
        changed = True
    ui = sys.modules.get(__package__ + '.notification_ui')
    if ui is not None:
        from . import runtime
        if not runtime.shell_interaction_busy():
            changed = ui.sync() or changed
    return changed


def snapshot():
    return copy.deepcopy(_state)


def icon_value(row):
    from . import icon_cache
    key = row.get('cache_key', '') if isinstance(row, dict) else ''
    return icon_cache.cached_value(key) if isinstance(key, str) and key.startswith(wire.PREFIX) else 0


def command(key, event, x, y):
    if (_owner is None or _owner.finished.is_set() or _owner.stopping.is_set() or
            time.monotonic() - _owner.last_received > 6):
        raise ValueError('Notification area is unavailable')
    value = wire.callback(key, event, x, y, _state)
    try:
        _owner.commands.put_nowait(value)
    except queue.Full:
        raise RuntimeError('Notification area is busy; try again') from None
    return True


def close():
    """No waits, file work or foreign process actions in shutdown/UI callbacks."""
    global _owner, _state, _pixels, _retry_at
    if _owner is not None:
        _owner.close()
        _retired.append(_owner)
        _owner = None
    _state, _pixels, _retry_at = wire.empty(), {}, 0.0
    _pending.clear()


atexit.register(close)
