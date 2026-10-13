# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolated desktop parenting service. Explicit reconcile is the only enable command."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blui_desktop.desktop_host_native import AbortEvent, DesktopWindows, OwnerProcess, SessionLock
from blui_desktop.desktop_host_state import Guard, Journal, surfaces
from blui_desktop.native_windows import _process_start

MAX_PACKET = 32768


def command(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid desktop host command')
    kind = value.get('command')
    if kind in ('heartbeat', 'shutdown') and set(value) == {'command'}:
        return value
    serial = value.get('serial')
    if type(serial) is not int or not 0 < serial < 1 << 53:
        raise ValueError('Invalid desktop host command serial')
    if kind == 'restore' and set(value) == {'command', 'serial'}:
        return value
    if kind == 'reconcile' and set(value) == {'command', 'serial', 'surfaces'}:
        return {'command': kind, 'serial': serial, 'surfaces': surfaces(value['surfaces'])}
    raise ValueError('Unsupported desktop host command')


def run(directory, pid, started):
    lock = owner = abort = guard = recovery = None
    eof, stopping = threading.Event(), threading.Event()
    inbox = queue.Queue(maxsize=32)
    failure = ''
    completed_serial = 0
    def reader():
        try:
            while not stopping.is_set():
                line = sys.stdin.buffer.readline(MAX_PACKET + 1)
                if not line or len(line) > MAX_PACKET or not line.endswith(b'\n'):
                    break
                try:
                    value = command(json.loads(line.decode('utf-8')))
                    inbox.put(value, timeout=.2)
                    if value['command'] == 'shutdown':
                        break
                except (ValueError, UnicodeError, queue.Full):
                    break  # Fail closed on malformed/unconsumed control data.
        finally:
            eof.set()
    def emit(value):
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
    try:
        lock = SessionLock()
        owner = OwnerProcess(pid, started)
        nonce = uuid.uuid4().hex
        abort = AbortEvent(nonce)
        backend = DesktopWindows(pid, started, abort)
        journal = Journal(directory)
        guard = Guard(backend, journal, nonce)
        if not guard.restore():
            raise RuntimeError('An earlier desktop restoration is still pending')
        # Publish this generation BEFORE the independent guard handshake.
        guard.value['nonce'] = nonce
        journal.write(guard.value)
        recovery = subprocess.Popen([sys.executable, '-I', '-B', '-u', '-X', 'utf8',
            os.path.join(os.path.dirname(__file__), 'desktop_host_recovery.py'), directory, nonce,
            str(pid), started, str(os.getpid()), _process_start(os.getpid())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ready = queue.Queue(maxsize=1)
        def read_ready():
            try:
                ready.put_nowait(recovery.stdout.readline(33))
            except (OSError, queue.Full):
                pass
        threading.Thread(target=read_ready, daemon=True).start()
        try:
            acknowledged = ready.get(timeout=5)
        except queue.Empty:
            acknowledged = b''
        if acknowledged != b'READY\n' or recovery.poll() is not None:
            raise RuntimeError('The independent desktop recovery guard is unavailable')
        recovery.stdout.close()
        threading.Thread(target=reader, name='BLUI desktop host commands', daemon=True).start()
        heartbeat = refresh = status_at = guardian_at = time.monotonic()
        previous = None
        while owner.alive() and not abort.aborted():
            if recovery.poll() is not None:
                raise RuntimeError('The independent desktop recovery guard exited')
            now = time.monotonic()
            if now - guardian_at >= .5:
                recovery.stdin.write(b'heartbeat\n')
                recovery.stdin.flush()
                guardian_at = now
            try:
                value = inbox.get(timeout=.05)
            except queue.Empty:
                if eof.is_set():
                    break
                value = None
            if value:
                kind = value['command']
                if kind == 'shutdown':
                    break
                if kind in ('heartbeat', 'reconcile'):
                    heartbeat = now
                if kind == 'reconcile':
                    guard.reconcile(value['surfaces'])
                    completed_serial = value['serial']
                elif kind == 'restore':
                    guard.restore()
                    completed_serial = value['serial']
            if now - heartbeat > 15:
                guard.error = 'BLUI is unresponsive; the original Windows desktop was restored'
                guard.need_rebind = True
                guard.restore()
            if now - refresh >= .3:
                guard.refresh()
                refresh = now
            status = guard.status()
            status['completed_serial'] = completed_serial
            if status != previous or now - status_at >= 2:
                emit(status)
                previous, status_at = status, now
    except Exception as exc:
        failure = str(exc)[:2048]
    finally:
        stopping.set()
        if abort:
            abort.set()
        if guard:
            for _ in range(10):
                try:
                    if guard.restore():
                        break
                except (OSError, RuntimeError, ValueError):
                    pass
                time.sleep(.1)
            result = guard.status()
        else:
            result = {'enabled': False, 'attached_count': 0, 'pending_restore': False,
                      'need_rebind': False, 'handles': [], 'state': 'Desktop Host Unavailable', 'error': ''}
        if failure:
            result['error'] = failure
        result['completed_serial'] = completed_serial
        try:
            emit(result)
        except (OSError, ValueError):
            pass
        # EOF tells the recovery process to replay any unresolved durable state.
        if recovery:
            try:
                recovery.stdin.close()
            except OSError:
                pass
        for resource in (abort, owner, lock):
            if resource:
                resource.close()


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit(2)
    try:
        run(sys.argv[1], int(sys.argv[2]), sys.argv[3])
    finally:
        # Only this owned helper exits, AFTER normal restoration/final status.
        os._exit(0)
