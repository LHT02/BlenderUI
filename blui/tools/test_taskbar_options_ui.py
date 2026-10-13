# SPDX-License-Identifier: GPL-2.0-or-later
"""Taskbar RNA adapter regressions with RNA doubles; no windows or file mutations."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
from blui_desktop import taskbar_settings as schema


class Service:
    def __init__(self):
        self.state, self.calls = schema.defaults(), []

    def values(self):
        return dict(self.state)

    def configure(self, **kwargs):
        self.calls.append(kwargs)
        self.state = schema.changed(self.state, **kwargs)

    def defaults(self):
        return schema.defaults()

    def error(self):
        return ''


class OptionsTests(unittest.TestCase):
    def setUp(self):
        props = ModuleType('bpy.props')
        for name in ('IntProperty', 'PointerProperty'):
            setattr(props, name, lambda **kwargs: kwargs)
        types = ModuleType('bpy.types')
        for name in ('Operator', 'PropertyGroup', 'WindowManager'):
            setattr(types, name, type(name, (), {}))
        self.bpy = ModuleType('bpy')
        self.bpy.types = types
        self.normal_area = SimpleNamespace(tag_redraw=mock.Mock())
        self.shell_area = SimpleNamespace(tag_redraw=mock.Mock())
        self.props = SimpleNamespace(height=56, icon_size=32)
        self.context = SimpleNamespace(window_manager=SimpleNamespace(
            blui_taskbar_options=self.props, windows=[
                SimpleNamespace(blui_shell_role='NORMAL', screen=SimpleNamespace(areas=[self.normal_area])),
                SimpleNamespace(blui_shell_role='TASKBAR', screen=SimpleNamespace(areas=[self.shell_area]))]))
        self.bpy.context = self.context
        with mock.patch.dict(sys.modules, {'bpy': self.bpy, 'bpy.props': props, 'bpy.types': types}):
            spec = importlib.util.spec_from_file_location('blui_desktop._taskbar_options_fixture',
                SOURCE / 'scripts/modules/blui_desktop/taskbar_options_ui.py')
            self.adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.adapter)
        self.service = Service()
        self.adapter.taskbar_settings = self.service

    def test_property_limits_defaults_and_callbacks(self):
        annotations = self.adapter.BLUI_TaskbarOptions.__annotations__
        height, icon = annotations['height'], annotations['icon_size']
        self.assertEqual((height['default'], height['min'], height['max']), (56, 32, 160))
        self.assertEqual((icon['default'], icon['min'], icon['max']), (32, 16, 64))
        self.assertEqual(height['options'], {'SKIP_SAVE'})
        self.assertEqual(icon['options'], {'SKIP_SAVE'})

    def test_icon_growth_canonicalizes_height_without_file_io(self):
        self.props.icon_size = 64
        with mock.patch('builtins.open', side_effect=AssertionError('RNA must not read/write files')), \
                mock.patch.object(Path, 'open', side_effect=AssertionError('RNA must not open files')):
            self.adapter._icon_changed(self.props, self.context)
        self.assertEqual(self.adapter.values(), {'height': 80, 'icon_size': 64})
        self.assertEqual((self.props.height, self.props.icon_size), (80, 64))
        self.assertEqual(self.service.calls, [{'icon_size': 64}])
        self.shell_area.tag_redraw.assert_called_once_with()
        self.normal_area.tag_redraw.assert_not_called()

    def test_minimum_height_keeps_icon_padding(self):
        self.props.height = 32
        self.adapter._height_changed(self.props, self.context)
        self.assertEqual(self.props.height, 48)
        self.assertEqual(self.props.icon_size, 32)

    def test_async_sync_is_read_only_and_does_not_increment_revision(self):
        self.service.state = {**schema.defaults(), 'height': 96, 'icon_size': 48, 'revision': 9}
        self.assertTrue(self.adapter.sync(self.context))
        self.assertEqual((self.props.height, self.props.icon_size), (96, 48))
        self.assertFalse(self.adapter.sync(self.context))
        self.assertEqual(self.service.calls, [])
        self.assertEqual(self.service.state['revision'], 9)

    def test_nested_rna_update_is_suppressed_during_canonical_sync(self):
        adapter, context = self.adapter, self.context
        class Reactive:
            def __init__(self):
                object.__setattr__(self, 'height', 56)
                object.__setattr__(self, 'icon_size', 32)
            def __setattr__(self, name, value):
                object.__setattr__(self, name, value)
                if name == 'height':
                    adapter._height_changed(self, context)
                elif name == 'icon_size':
                    adapter._icon_changed(self, context)
        reactive = Reactive()
        context.window_manager.blui_taskbar_options = reactive
        reactive.icon_size = 64
        self.assertEqual((reactive.height, reactive.icon_size), (80, 64))
        self.assertEqual(self.service.calls, [{'icon_size': 64}])
        self.assertFalse(adapter._syncing)

    def test_values_are_defensive_and_do_not_leak_revision(self):
        value = self.adapter.values(self.context)
        value['height'] = 160
        self.assertEqual(self.adapter.values(), {'height': 56, 'icon_size': 32})

    def test_reset_uses_same_memory_only_update_path(self):
        self.service.state = {**schema.defaults(), 'height': 120, 'icon_size': 48}
        self.adapter.sync(self.context)
        operator = self.adapter.WM_OT_blui_taskbar_appearance_reset()
        self.assertEqual(operator.execute(self.context), {'FINISHED'})
        self.assertEqual(self.adapter.values(), {'height': 56, 'icon_size': 32})
        self.assertEqual(self.service.calls, [{'height': 56, 'icon_size': 32}])

    def test_absent_window_manager_sync_is_safe(self):
        self.assertFalse(self.adapter.sync(SimpleNamespace()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
