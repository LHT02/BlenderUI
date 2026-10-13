# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure notification receiver forwarding/lifecycle mocks, never starts the host."""
import ctypes as c
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import native_windows, notification_host as module

OWN = (os.getpid(), 2, '3', 'Shell_TrayWnd')
EXPLORER = (10, 20, '30', 'Shell_TrayWnd')


class HostTests(unittest.TestCase):
    def setUp(self):
        self.host = module.Host.__new__(module.Host)
        self.host.tray, self.host.notify = 100, 101
        self.host.original = (200, EXPLORER)
        self.host.private = False
        self.host.error = ''
        self.host.classes, self.host.instance = ['Shell_TrayWnd', 'TrayNotifyWnd'], 500
        self.host.broadcasted, self.host.lock = True, 600
        self.host.user = SimpleNamespace(SetWindowPos=mock.Mock(return_value=True),
            DestroyWindow=mock.Mock(return_value=True), UnregisterClassW=mock.Mock(return_value=True),
            SendMessageTimeoutW=mock.Mock(return_value=True), DefWindowProcW=mock.Mock(return_value=0),
            PostMessageW=mock.Mock(return_value=True), AllowSetForegroundWindow=mock.Mock(return_value=True))
        self.host.kernel = SimpleNamespace(CloseHandle=mock.Mock(return_value=True))
        self.host.store = mock.Mock()
        self.host.history, self.host.build = None, 19045

    def test_restoration_after_owned_windows_destroyed_only(self):
        events = []
        self.host.user.DestroyWindow.side_effect = lambda handle: events.append(('destroy', handle))
        self.host._broadcast = lambda: events.append(('broadcast', self.host.tray))
        self.host.close()
        self.assertEqual(events, [('destroy', 101), ('destroy', 100), ('broadcast', None)])
        self.assertIsNone(self.host.tray)
        self.assertIsNone(self.host.notify)
        self.host.kernel.CloseHandle.assert_called_once_with(600)

    def test_private_host_never_broadcasts_or_forwards(self):
        self.host.private, self.host.broadcasted = True, False
        self.host._broadcast = mock.Mock()
        self.assertEqual(self.host._forward(0x4a, 0, 123), 0)
        self.host.user.SendMessageTimeoutW.assert_not_called()
        self.host.close()
        self.host._broadcast.assert_not_called()

    def test_raise_only_owned_receiver_not_explorer(self):
        with mock.patch.object(native_windows, '_identity', return_value=OWN):
            self.host._raise_own()
        self.assertEqual(self.host.user.SetWindowPos.call_args.args[:2], (100, -1))
        self.assertNotIn(200, self.host.user.SetWindowPos.call_args.args[:1])

    def test_reused_receiver_handle_never_restacked(self):
        with mock.patch.object(native_windows, '_identity', return_value=EXPLORER):
            with self.assertRaises(RuntimeError):
                self.host._raise_own()
        self.host.user.SetWindowPos.assert_not_called()

    def test_forward_requires_fresh_matching_explorer_identity(self):
        with mock.patch.object(native_windows, '_identity', return_value=EXPLORER):
            self.host._forward(0x4a, 300, 400)
        self.assertEqual(self.host.user.SendMessageTimeoutW.call_args.args[:4], (200, 0x4a, 300, 400))
        self.assertEqual(self.host.user.SendMessageTimeoutW.call_args.args[5], 250)

    def test_stale_explorer_never_receives_packet(self):
        self.host._find_explorer = mock.Mock(return_value=None)
        with mock.patch.object(native_windows, '_identity', return_value=None):
            self.assertEqual(self.host._forward(0x4a, 300, 400), 0)
        self.host.user.SendMessageTimeoutW.assert_not_called()

    def test_copydata_size_invalid_never_reads_pointer_or_forwards(self):
        self.host._forward = mock.Mock()
        data = module._CopyData(1, 4097, c.c_void_p(1))
        self.assertEqual(self.host._message(100, 0x4a, 0, c.addressof(data)), 0)
        self.host.store.apply.assert_not_called()
        self.host._forward.assert_not_called()

    def test_copydata_valid_packet_stored_and_forwarded(self):
        self.host._forward = mock.Mock(return_value=1)
        data = bytearray(964)
        struct.pack_into('<8I', data, 0, 0, 0, 956, 300, 42, 1, 0x8001, 400)
        buffer = c.create_string_buffer(bytes(data))
        copy = module._CopyData(1, len(data), c.cast(buffer, c.c_void_p))
        self.assertEqual(self.host._message(100, 0x4a, 300, c.addressof(copy)), 1)
        self.assertEqual(self.host.store.apply.call_args.args[0]['handle'], 300)
        self.host._forward.assert_called_once_with(0x4a, 300, c.addressof(copy))

    def test_unknown_command_does_not_dispatch_callbacks(self):
        for value in ('shutdown', None, {'command': 'launch'}, {'command': 'activate', 'key': None}):
            with self.assertRaises(ValueError):
                self.host.command(value)
        self.host.store.action.assert_not_called()
        self.assertFalse(self.host.command({'command': 'shutdown'}))


if __name__ == '__main__':
    unittest.main()
