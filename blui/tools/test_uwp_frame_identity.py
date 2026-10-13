# SPDX-License-Identifier: GPL-2.0-or-later
"""Broker/CoreWindow AUMID collection using only mocked identities and APIs."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import native_windows

APP = 'Example.Package_abcd123456789!ExampleApp'
ROOT = (10, 20, '30', 'ApplicationFrameWindow')
CHILD = (11, 21, '31', 'Windows.UI.Core.CoreWindow')
BROKER = {'executable': r'C:\Windows\System32\ApplicationFrameHost.exe', 'app_id': ''}


class BrokerIdentityTests(unittest.TestCase):
    def run_lookup(self, children, identities, metadata=None, *, root_identity=ROOT):
        enumerated = []
        def enumerate_children(handle, callback, parameter):
            enumerated.append(handle)
            for child in children:
                if not callback(child, parameter):
                    break
            return True
        user = SimpleNamespace(EnumChildWindows=enumerate_children)
        values = {11: {'executable': r'C:\WindowsApps\App.exe', 'app_id': APP}, **(metadata or {})}
        def identity(_user, handle, *args):
            return root_identity if handle == 1 else identities.get(handle)
        # Python callable callbacks suffice; no OS calls or actual HWNDs.
        with mock.patch.object(native_windows.c, 'WINFUNCTYPE', return_value=lambda callback: callback, create=True), \
             mock.patch.object(native_windows, '_identity', side_effect=identity), \
             mock.patch.object(native_windows, '_metadata', side_effect=lambda pid: values[pid]):
            result = native_windows._window_app_id(user, 1, ROOT, BROKER, {}, {})
        return result, enumerated

    def test_broker_uses_verified_corewindow_application_identity(self):
        value, calls = self.run_lookup([2], {2: CHILD})
        self.assertEqual(value, APP)
        self.assertEqual(calls, [1])

    def test_ambiguous_child_apps_do_not_inherit_wrong_icon(self):
        second = (12, 22, '32', 'Windows.UI.Core.CoreWindow')
        value, _ = self.run_lookup([2, 3], {2: CHILD, 3: second},
                                  {12: {'app_id': 'Other.Package_abcd123456789!Other'}})
        self.assertEqual(value, '')

    def test_broker_changed_before_enumeration_does_not_read_child(self):
        value, calls = self.run_lookup([2], {2: CHILD}, root_identity=(10, 20, '999', ROOT[3]))
        self.assertEqual(value, '')
        self.assertEqual(calls, [])

    def test_invalid_and_non_corewindow_child_not_used(self):
        for child in (None, (11, 21, '', CHILD[3]), (11, 21, '31', 'UnrelatedWindow'),
                      (10, 21, '31', CHILD[3])):
            value, _ = self.run_lookup([2], {2: child})
            self.assertEqual(value, '')
        value, _ = self.run_lookup([2], {2: CHILD}, {11: {'app_id': 'not-a-package'}})
        self.assertEqual(value, '')

    def test_child_enumeration_has_a_hard_limit(self):
        value, _ = self.run_lookup(list(range(2, 80)), {70: CHILD})
        self.assertEqual(value, '')
        value, _ = self.run_lookup(list(range(2, 80)), {2: CHILD, 70: CHILD})
        self.assertEqual(value, '', 'a truncated child list cannot prove uniqueness')

    def test_child_changed_after_metadata_is_not_adopted(self):
        def enumerate_children(handle, callback, parameter):
            callback(2, parameter)
            return True
        user = SimpleNamespace(EnumChildWindows=enumerate_children)
        count = 0
        def identity(_user, handle, *args):
            nonlocal count
            if handle == 1:
                return ROOT
            count += 1
            return CHILD if count <= 2 else (11, 21, 'changed', CHILD[3])
        with mock.patch.object(native_windows.c, 'WINFUNCTYPE', return_value=lambda callback: callback, create=True), \
             mock.patch.object(native_windows, '_identity', side_effect=identity), \
             mock.patch.object(native_windows, '_metadata', return_value={'app_id': APP}):
            self.assertEqual(native_windows._window_app_id(user, 1, ROOT, BROKER, {}, {}), '')

    def test_process_aumid_does_not_require_broker_lookup(self):
        user = SimpleNamespace()
        self.assertEqual(native_windows._window_app_id(user, 1, ROOT, {'app_id': APP}, {}, {}), APP)
        self.assertEqual(native_windows._window_app_id(user, 1, (10, 20, '30', 'OtherWindow'), BROKER, {}, {}), '')


if __name__ == '__main__':
    unittest.main()
