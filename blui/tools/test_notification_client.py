# SPDX-License-Identifier: GPL-2.0-or-later
"""Notification IPC/RAM regressions. Never creates a native notification host."""
import base64
import copy
import io
import json
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
import blui_desktop
from blui_desktop import notification_client as client, notification_wire as wire


def row(uid=1, *, pixels=False, hidden=False):
    return {'key': 'hwnd:100:' + str(uid), 'handle': '100', 'uid': uid, 'guid': '',
        'callback': 0x401, 'version': 4, 'tip': 'Fixture ' + str(uid), 'hidden': hidden,
        'width': 32 if pixels else 0, 'height': 32 if pixels else 0,
        'rgba': base64.b64encode(bytes([uid % 256, 0, 0, 255]) * 1024).decode('ascii') if pixels else '',
        'pid': 200, 'thread_id': 300, 'process_started': '400', 'window_class': 'Fixture'}


def snapshot(rows=None):
    return {'enabled': True, 'error': '', 'revision': 1, 'host_handle': '500', 'icons': rows or [row()]}


class WireTests(unittest.TestCase):
    def test_metadata_has_no_pixels_and_preview_is_content_addressed(self):
        value, pixels = wire.validate_snapshot(snapshot([row(pixels=True)]))
        icon = value['icons'][0]
        self.assertNotIn('rgba', icon)
        self.assertTrue(icon['cache_key'].startswith(wire.PREFIX))
        self.assertEqual(pixels[icon['cache_key']]['width'], 32)
        duplicate = row(2, pixels=True)
        duplicate['rgba'] = row(1, pixels=True)['rgba']
        value, pixels = wire.validate_snapshot(snapshot([row(pixels=True), duplicate]))
        self.assertEqual(len(pixels), 1)
        self.assertEqual(value['icons'][0]['cache_key'], value['icons'][1]['cache_key'])

    def test_duplicate_keys_invalid_identity_and_callback_rejected(self):
        with self.assertRaises(ValueError):
            wire.validate_snapshot(snapshot([row(), row()]))
        for name, bad in (('handle', '0'), ('pid', True), ('thread_id', 0),
                ('process_started', '-1'), ('window_class', ''), ('key', 'hwnd:other'),
                ('callback', 0x20), ('version', 5), ('hidden', 1), ('tip', 'x' * 128),
                ('width', 64), ('rgba', 'not-base64'), ('uid', -1)):
            candidate = row()
            candidate[name] = bad
            with self.subTest(name=name), self.assertRaises(ValueError):
                wire.validate_snapshot(snapshot([candidate]))

    def test_header_and_total_budget_are_strict(self):
        for name, bad in (('enabled', 1), ('revision', True), ('host_handle', '0'),
                          ('icons', [row()] * 129), ('error', 'x' * 1025)):
            value = snapshot()
            value[name] = bad
            with self.subTest(name=name), self.assertRaises(ValueError):
                wire.validate_snapshot(value)
        value = wire.empty()
        value['icons'] = [row()]
        with self.assertRaises(ValueError):
            wire.validate_snapshot(value)
        self.assertEqual(wire.validate_snapshot(wire.empty()), (wire.empty(), {}))

    def test_partial_and_inconsistent_pixels_rejected(self):
        for width, height, rgba in ((32, 0, ''), (0, 32, ''), (32, 32, ''),
                                   (0, 0, base64.b64encode(b'four').decode('ascii'))):
            candidate = dict(row(), width=width, height=height, rgba=rgba)
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                wire.validate_snapshot(snapshot([candidate]))

    def test_only_existing_icon_and_fixed_mouse_event_can_be_sent(self):
        value, _pixels = wire.validate_snapshot(snapshot())
        for event in wire.EVENTS:
            self.assertEqual(wire.callback(row()['key'], event, -20, 30, value),
                {'command': 'activate', 'key': row()['key'], 'event': event, 'x': -20, 'y': 30})
        for key, event, x, y in (('other', 'LEFT', 0, 0), (row()['key'], 'CMD', 0, 0),
                (row()['key'], 'LEFT', True, 0), (row()['key'], 'LEFT', 32768, 0)):
            with self.assertRaises(ValueError):
                wire.callback(key, event, x, y, value)
        with self.assertRaises(ValueError):
            wire.callback(row()['key'], 'LEFT', 0, 0, wire.empty())


class Owner:
    def __init__(self):
        self.commands, self.updates = queue.Queue(maxsize=32), queue.Queue(maxsize=2)
        self.finished, self.stopping = threading.Event(), threading.Event()
        self.last_received = time.monotonic()
    def close(self):
        self.stopping.set()


class ClientTests(unittest.TestCase):
    def setUp(self):
        client.close()
        client._retired.clear()
        self.owner = Owner()
        client._owner = self.owner
        self.cached = {}
        self.batches = []
        def apply(rows):
            self.batches.append(copy.deepcopy(rows))
            for item in rows:
                self.cached[item['path']] = len(self.cached) + 1
        self.cache = SimpleNamespace(cached_value=lambda key: self.cached.get(key, 0), apply=apply)
        self.patch = mock.patch.object(blui_desktop, 'icon_cache', self.cache, create=True)
        self.patch.start()
    def tearDown(self):
        client.close()
        client._retired.clear()
        self.patch.stop()

    def _receive(self, value):
        self.owner.updates.put(wire.validate_snapshot(value))

    def test_poll_applies_only_eight_and_reuses_cached_content(self):
        self._receive(snapshot([row(uid, pixels=True) for uid in range(1, 11)]))
        self.assertTrue(client.poll())
        self.assertEqual(len(self.batches[0]), 8)
        self.assertTrue(client.poll())
        self.assertEqual(len(self.batches[1]), 2)
        self.assertFalse(client.poll())
        self._receive(snapshot([row(uid, pixels=True) for uid in range(1, 11)]))
        client.poll()
        self.assertEqual(len(self.batches), 2)
        icon = client.snapshot()['icons'][0]
        self.assertGreater(client.icon_value(icon), 0)

    def test_evicted_preview_is_recreated_from_ram_without_file_queue(self):
        self._receive(snapshot([row(pixels=True)]))
        client.poll()
        self.cached.clear()
        self.assertEqual(client.icon_value(client.snapshot()['icons'][0]), 0)
        self.assertTrue(client.poll())
        self.assertEqual(len(self.batches), 2)

    def test_snapshot_is_defensive_and_command_is_nonblocking(self):
        self._receive(snapshot())
        client.poll()
        value = client.snapshot()
        value['icons'][0]['key'] = 'injected'
        self.assertTrue(client.command(row()['key'], 'RIGHT', 0, 0))
        self.assertEqual(self.owner.commands.get_nowait()['event'], 'RIGHT')
        with self.assertRaises(ValueError):
            client.command('injected', 'RIGHT', 0, 0)

    def test_full_queue_or_dead_helper_fails_closed(self):
        self._receive(snapshot())
        client.poll()
        for _ in range(32):
            self.owner.commands.put({'command': 'heartbeat'})
        with self.assertRaises(RuntimeError):
            client.command(row()['key'], 'LEFT', 0, 0)
        self.owner.stopping.set()
        with self.assertRaises(ValueError):
            client.command(row()['key'], 'LEFT', 0, 0)

    def test_stale_snapshot_disables_icons_and_closes_only_own_helper(self):
        self._receive(snapshot())
        client.poll()
        self.owner.last_received -= 7
        with self.assertRaises(ValueError):
            client.command(row()['key'], 'LEFT', 0, 0)
        self.assertTrue(client.poll())
        self.assertFalse(client.snapshot()['enabled'])
        self.assertTrue(self.owner.stopping.is_set())

    def test_close_clears_ram_without_waiting_and_ignores_old_mailbox(self):
        self._receive(snapshot())
        client.poll()
        client.close()
        self.owner.updates.put(wire.validate_snapshot(snapshot()))
        self.assertFalse(client.poll())
        self.assertEqual(client.snapshot(), wire.empty())
        self.assertTrue(self.owner.stopping.is_set())

    def test_private_qa_guard_never_starts_real_host(self):
        client.close()
        client._retired.clear()
        session = SimpleNamespace(disable_for_tests=True)
        with mock.patch.object(blui_desktop, 'session', session, create=True), \
                mock.patch.object(client, '_Owner') as owned, \
                mock.patch.dict(client.os.environ, {'BLUI_NOTIFY_QA_PRIVATE': '0'}):
            self.assertFalse(client.start())
            owned.assert_not_called()
            with mock.patch.dict(client.os.environ, {'BLUI_NOTIFY_QA_PRIVATE': '1'}):
                self.assertTrue(client.start())
            owned.assert_called_once_with(True)
        client._owner = None

    def test_pipe_reader_rejects_invalid_utf8_without_native_process(self):
        owner = client._Owner.__new__(client._Owner)
        owner.updates, owner.stopping, owner.error = queue.Queue(maxsize=2), threading.Event(), ''
        owner.last_received = time.monotonic()
        process = SimpleNamespace(stdout=io.BytesIO(b'\xff\n'))
        owner._read(process)
        value, _pixels = owner.updates.get_nowait()
        self.assertFalse(value['enabled'])
        self.assertTrue(owner.stopping.is_set())
        self.assertTrue(process.stdout.closed)

    def test_pipe_reader_has_four_megabyte_limit_and_no_unbounded_read(self):
        owner = client._Owner.__new__(client._Owner)
        owner.updates, owner.stopping, owner.error = queue.Queue(maxsize=2), threading.Event(), ''
        owner.last_received = time.monotonic()
        class Pipe:
            closed = False
            def readline(self, size):
                self.size = size
                return b'x' * size
            def close(self):
                self.closed = True
        pipe = Pipe()
        owner._read(SimpleNamespace(stdout=pipe))
        self.assertEqual(pipe.size, wire.MAX_BYTES + 1)
        self.assertTrue(owner.stopping.is_set())
        self.assertTrue(pipe.closed)
        value, _pixels = owner.updates.get_nowait()
        self.assertFalse(value['enabled'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
