# SPDX-License-Identifier: GPL-2.0-or-later
"""OWN-PID real notification receive/raster/callback QA. Root runs this serially.

Creates ONLY private hidden QA classes. NEVER broadcasts TaskbarCreated, modifies
Explorer/system tray state, triggers other application callbacks, or launches apps.
Run with the bundled Python, not inside an existing user's BLUI process.
"""
import base64
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import native_windows, notification_host

CALLBACK = 0x8001


def payload(owner, icon, message=0, tip='BLUI QA 通知图标', *, version=0):
    assert 0 < owner <= 0xffffffff and 0 < icon <= 0xffffffff
    data = bytearray(964)
    struct.pack_into('<8I', data, 0, 0, message, 956, owner, 42, 7, CALLBACK, icon)
    encoded = (tip + '\x00').encode('utf-16-le')
    data[32:32 + len(encoded)] = encoded
    struct.pack_into('<I', data, 808, version)
    return bytes(data)


def main():
    if os.name != 'nt':
        raise SystemExit('Windows-only owned notification QA')
    own = notification_host.Host(private=True)
    original = own._message
    callbacks = []
    def receive(handle, message, wparam, lparam):
        if message == CALLBACK:
            callbacks.append((int(wparam), int(lparam)))
            return 0
        return original(handle, message, wparam, lparam)
    own._wndproc = own._wndproc_type(receive)
    own.open()
    root_identity = native_windows._identity(own.user, own.tray)
    assert root_identity and root_identity[0] == os.getpid()
    own.user.LoadIconW.argtypes, own.user.LoadIconW.restype = [w.HINSTANCE, c.c_void_p], w.HICON
    icon = own.user.LoadIconW(None, c.c_void_p(32512))
    assert icon
    inbox = queue.Queue()
    child = subprocess.Popen([sys.executable, '-I', '-B', '-u', str(Path(notification_host.__file__)),
        str(os.getpid()), native_windows._process_start(os.getpid()), '--qa-private'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    def read():
        for line in iter(child.stdout.readline, b''):
            inbox.put(json.loads(line.decode('utf-8')))
    threading.Thread(target=read, daemon=True).start()
    latest = None
    def wait(predicate, timeout=8):
        nonlocal latest
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            own.pump(time.monotonic())
            while not inbox.empty():
                latest = inbox.get_nowait()
            if predicate(latest):
                return latest
            if child.poll() is not None:
                raise AssertionError('QA helper exited: ' + child.stderr.read().decode('utf-8', 'replace'))
            time.sleep(.01)
        raise AssertionError(('notification host QA timed out', latest, callbacks))
    try:
        initial = wait(lambda value: value and value['enabled'])
        target = int(initial['host_handle'])
        identity = native_windows._identity(own.user, target)
        assert identity and identity[0] == child.pid and identity[3] == 'BLUI_QA_NotificationHost'
        def send(data):
            assert native_windows._identity(own.user, target) == identity, 'only exact QA child may receive packets'
            buffer = c.create_string_buffer(data)
            packet = notification_host._CopyData(1, len(data), c.cast(buffer, c.c_void_p))
            result = c.c_size_t()
            assert own.user.SendMessageTimeoutW(target, 0x4a, own.tray, c.addressof(packet), 0x3, 1000, c.byref(result))
            assert result.value == 1
        send(payload(own.tray, icon))
        first = wait(lambda value: value and len(value['icons']) == 1)['icons'][0]
        assert first['pid'] == os.getpid() and first['handle'] == str(own.tray)
        assert first['tip'] == 'BLUI QA 通知图标'
        assert first['width'] == first['height'] == 32
        rgba = base64.b64decode(first['rgba'], validate=True)
        assert len(rgba) == 32 * 32 * 4 and any(rgba[index] for index in range(3, len(rgba), 4))
        send(payload(own.tray, icon, 1, tip='BLUI QA 更新'))
        wait(lambda value: value and value['icons'] and value['icons'][0]['tip'] == 'BLUI QA 更新')
        send(payload(own.tray, icon, 4, version=4))
        wait(lambda value: value and value['icons'] and value['icons'][0]['version'] == 4)
        command = {'command': 'activate', 'key': first['key'], 'event': 'RIGHT', 'x': -100, 'y': -40}
        child.stdin.write((json.dumps(command) + '\n').encode('utf-8'))
        child.stdin.flush()
        wait(lambda value: len(callbacks) >= 3)
        assert [message & 0xffff for _position, message in callbacks[-3:]] == [0x204, 0x205, 0x7b]
        assert all(message >> 16 == 42 for _position, message in callbacks[-3:])
        assert all(position & 0xffff == (-100 & 0xffff) and position >> 16 == (-40 & 0xffff)
                   for position, _message in callbacks[-3:])
        send(payload(own.tray, icon, 2))
        wait(lambda value: value and value['revision'] >= 4 and value['icons'] == [])
        child.stdin.write(b'{"command":"shutdown"}\n')
        child.stdin.flush()
        assert child.wait(timeout=4) == 0
        assert not own.user.IsWindow(target), 'owned helper window must be destroyed on shutdown'
        print('check_notification_host: PASS (OWN-only real ADD/MODIFY/DELETE/version4 callbacks, UTF8, RGBA, cleanup; no broadcast/Explorer changes)')
    finally:
        if child.poll() is None:
            child.stdin.close()  # EOF; no process kill, helper owns its own cleanup.
            child.wait(timeout=4)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream and not stream.closed:
                stream.close()
        own.close()


if __name__ == '__main__':
    main()
