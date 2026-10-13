# SPDX-License-Identifier: GPL-2.0-or-later
"""Power tests never call real suspend/shutdown/configuration APIs."""
import ast
from contextlib import nullcontext
import ctypes as c
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
from blui_desktop import system_power as power, power_state as cache
from blui_desktop import power_clock


class PowerTests(unittest.TestCase):
    def test_hibernate_deadline_uses_awake_time_only_in_worker(self):
        values = iter((1_000_000, 1_200_000, 1_200_000, 1_400_000))
        def query(pointer):
            c.cast(pointer, c.POINTER(c.c_ulonglong)).contents.value = next(values)
            return True
        api = SimpleNamespace(QueryUnbiasedInterruptTime=mock.Mock(side_effect=query))
        with mock.patch.object(c, 'WinDLL', return_value=api):
            clock = power_clock.active_clock()
            self.assertEqual(clock(), clock())  # A suspended interval adds no awake ticks.
            self.assertAlmostEqual(clock(), .14)
        source = (SOURCE / 'scripts/modules/blui_desktop/client.py').read_text(encoding='utf-8')
        self.assertIn("self._request['args'] == ['HIBERNATE']", source)
        self.assertIn('clock() - started > self.timeout', source)

    def test_sdk_layout_offsets(self):
        self.assertEqual(c.sizeof(power._Capabilities), 76)
        self.assertEqual(power._Capabilities.SystemS4.offset, 6)
        self.assertEqual(power._Capabilities.HiberFilePresent.offset, 8)
        self.assertEqual(power._Capabilities.HiberFileType.offset, 22)
        self.assertEqual(power._Capabilities.BatteryScale.offset, 32)

    def test_only_s4_and_full_present_hiberfile_exposes_hibernate(self):
        for s4 in (0, 1):
            for present in (0, 1):
                for file_type in (0, 1, 2, 3):
                    def query(pointer):
                        value = c.cast(pointer, c.POINTER(power._Capabilities)).contents
                        value.SystemS4, value.HiberFilePresent, value.HiberFileType = s4, present, file_type
                        return True
                    suspend = mock.Mock(side_effect=AssertionError('Detection cannot suspend'))
                    with mock.patch.object(power, '_api', return_value=SimpleNamespace(GetPwrCapabilities=query, SetSuspendState=suspend)):
                        self.assertEqual(power.capabilities(), {'hibernate': bool(s4 and present and file_type == 2)})
                    suspend.assert_not_called()

    def test_disabled_capability_never_enables_privilege_or_suspends(self):
        with mock.patch.object(power, 'capabilities', return_value={'hibernate': False}), \
                mock.patch.object(power, '_shutdown_privilege') as privilege, \
                mock.patch.object(power, '_api') as api:
            with self.assertRaisesRegex(ValueError, 'not enabled'):
                power.hibernate()
            privilege.assert_not_called()
            api.assert_not_called()

    def test_confirmed_hibernate_rechecks_and_keeps_wake_events(self):
        suspend = mock.Mock(return_value=True)
        with mock.patch.object(power, 'capabilities', return_value={'hibernate': True}) as check, \
                mock.patch.object(power, '_shutdown_privilege', return_value=nullcontext()) as privilege, \
                mock.patch.object(power, '_api', return_value=SimpleNamespace(SetSuspendState=suspend)):
            self.assertTrue(power.hibernate())
        check.assert_called_once_with()
        privilege.assert_called_once_with()
        suspend.assert_called_once_with(True, False, False)

    def test_capabilities_protocol_fail_closed(self):
        for value in ({}, {'hibernate': 1}, {'hibernate': True, 'execute': True}, [], None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                power.validate(value)
        value = {'hibernate': True}
        self.assertEqual(power.validate(value), value)
        self.assertIsNot(power.validate(value), value)

    def test_hibernate_uses_confirmation_and_save_warning(self):
        module = ast.parse((SOURCE / 'scripts/modules/blui_desktop/start_menu_ui.py').read_text(encoding='utf-8'))
        kind = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'WM_OT_blui_start_system')
        methods = [node for node in kind.body if isinstance(node, ast.FunctionDef) and node.name in {'invoke', 'draw'}]
        namespace = {'iface': lambda value: value}
        exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])), '<real-power-ui>', 'exec'), namespace)
        dialog = mock.Mock(return_value={'RUNNING_MODAL'})
        executed = mock.Mock(side_effect=AssertionError('Unconfirmed action cannot execute'))
        labels = []
        owner = SimpleNamespace(action='HIBERNATE', execute=executed,
                                layout=SimpleNamespace(label=lambda **kw: labels.append(kw['text'])))
        context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        self.assertEqual(namespace['invoke'](owner, context, None), {'RUNNING_MODAL'})
        namespace['draw'](owner, context)
        self.assertIn('Hibernate Windows?', labels)
        self.assertIn('Save your work before continuing', labels)
        executed.assert_not_called()

    def test_power_menu_is_conditional_and_draw_only_reads_ram(self):
        module = ast.parse((SOURCE / 'scripts/modules/blui_desktop/start_menu_ui.py').read_text(encoding='utf-8'))
        menu = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'BLUI_MT_start_power')
        draw = next(node for node in menu.body if isinstance(node, ast.FunctionDef) and node.name == 'draw')
        namespace = {'__package__': 'blui_desktop', 'iface': lambda value: value}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[draw], type_ignores=[])), '<real-power-menu>', 'exec'), namespace)
        for enabled in (False, True):
            buttons = []
            def operator(name, **kwargs):
                self.assertEqual(name, 'wm.blui_start_system')
                button = SimpleNamespace(**kwargs)
                buttons.append(button)
                return button
            owner = SimpleNamespace(layout=SimpleNamespace(operator=operator))
            with mock.patch.object(cache, 'snapshot', return_value={'hibernate': enabled}), \
                    mock.patch.object(power, '_api', side_effect=AssertionError('Menu draw cannot query Windows')):
                namespace['draw'](owner, None)
            self.assertEqual(any(button.action == 'HIBERNATE' for button in buttons), enabled)
            self.assertEqual(owner.layout.operator_context, 'INVOKE_DEFAULT')


class Job:
    def __init__(self, *_args, **_kwargs):
        self.ready = False
        self.value = {'hibernate': True}
        self.closed = False
    def done(self):
        return self.ready
    def result(self):
        return self.value
    def close(self):
        self.closed = True


class CacheTests(unittest.TestCase):
    def setUp(self):
        cache.close()
        self.job = Job()
        self.patch = mock.patch.object(cache.client, 'Job', return_value=self.job)
        self.launch = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(cache.close)

    def test_single_flight_no_job_from_closed_menu(self):
        cache.tick(False)
        self.launch.assert_not_called()
        cache.tick(True)
        cache.tick(True)
        self.launch.assert_called_once_with('start_capabilities', timeout=4)
        self.assertFalse(cache.snapshot()['hibernate'])
        self.job.ready = True
        self.assertTrue(cache.tick(True))
        self.assertTrue(cache.snapshot()['hibernate'])
        self.assertTrue(self.job.closed)
        self.launch.assert_called_once()

    def test_invalid_or_failed_reply_hides_item(self):
        cache.tick(True)
        cache._value = {'hibernate': True}
        self.job.ready, self.job.value = True, {'hibernate': 1}
        self.assertTrue(cache.tick(False))
        self.assertFalse(cache.snapshot()['hibernate'])

    def test_close_cancels_and_clears_previous_capability(self):
        cache.tick(True)
        cache._value = {'hibernate': True}
        cache.close()
        self.assertTrue(self.job.closed)
        self.assertEqual(cache.snapshot(), {'hibernate': False})


if __name__ == '__main__':
    unittest.main()
