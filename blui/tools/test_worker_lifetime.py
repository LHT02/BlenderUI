# SPDX-License-Identifier: GPL-2.0-or-later
"""Helper ownership never kills parents or unrelated processes, including PID reuse."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_explorer import worker_lifetime as lifetime


class WorkerLifetime(unittest.TestCase):
    def test_signaled_original_parent_exits_only_self_and_releases_handle(self):
        kernel = mock.Mock()
        kernel.WaitForSingleObject.return_value = 0
        with mock.patch.object(lifetime.os, '_exit', side_effect=SystemExit) as leave:
            with self.assertRaises(SystemExit):
                lifetime._wait(kernel, 77)
            leave.assert_called_once_with(0)
        kernel.WaitForSingleObject.assert_called_once_with(77, 0xffffffff)
        kernel.CloseHandle.assert_called_once_with(77)

    def test_wait_error_is_not_permission_to_kill_self(self):
        kernel = mock.Mock()
        kernel.WaitForSingleObject.return_value = 0xffffffff
        with mock.patch.object(lifetime.os, '_exit') as leave:
            lifetime._wait(kernel, 77)
            leave.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(77)

    def test_parent_access_is_readonly_synchronize_and_no_pid_repoll(self):
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 77
        with (mock.patch.object(lifetime.ctypes, 'WinDLL', return_value=kernel),
              mock.patch.object(lifetime.os, 'getppid', return_value=123) as parent,
              mock.patch.object(lifetime.os, 'getpid', return_value=456),
              mock.patch.object(lifetime.threading, 'Thread') as thread):
            self.assertTrue(lifetime.start())
            parent.assert_called_once()
            kernel.OpenProcess.assert_called_once_with(0x00100000, False, 123)
            self.assertEqual(thread.call_args.kwargs['args'], (kernel, 77))
            self.assertTrue(thread.call_args.kwargs['daemon'])
            thread.return_value.start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
