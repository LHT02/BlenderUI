# SPDX-License-Identifier: GPL-2.0-or-later
"""Notification sizing/render adapters with RNA doubles; no native app actions."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
import blui_desktop


class Items(list):
    def add(self):
        item = SimpleNamespace()
        self.append(item)
        return item


class Layout:
    def __init__(self, calls=None):
        self.calls = calls if calls is not None else []
    def row(self, **_kwargs):
        return Layout(self.calls)
    def operator(self, name, **kwargs):
        value = SimpleNamespace()
        self.calls.append((name, kwargs, value))
        return value


def icon(key, hidden=False):
    return {'key': key, 'tip': key + ' title', 'hidden': hidden, 'callback': 0x400,
            'cache_key': 'blui-notification:' + key}


class NotificationUITests(unittest.TestCase):
    def setUp(self):
        props, types = ModuleType('bpy.props'), ModuleType('bpy.types')
        for name in ('CollectionProperty', 'IntProperty', 'PointerProperty', 'StringProperty'):
            setattr(props, name, lambda **kwargs: kwargs)
        for name in ('Operator', 'PropertyGroup', 'UIList', 'WindowManager'):
            setattr(types, name, type(name, (), {}))
        self.bpy = ModuleType('bpy')
        self.bpy.types = types
        settings = SimpleNamespace(items=Items(), active=-1, as_pointer=lambda: 123)
        self.context = SimpleNamespace(window_manager=SimpleNamespace(blui_notification_settings=settings))
        self.bpy.context = self.context
        windows = SimpleNamespace()
        with mock.patch.dict(sys.modules, {'bpy': self.bpy, 'bpy.props': props, 'bpy.types': types}), \
                mock.patch.object(blui_desktop, 'taskbar_windows', windows, create=True):
            spec = importlib.util.spec_from_file_location('blui_desktop._notification_ui_fixture',
                SOURCE / 'scripts/modules/blui_desktop/notification_ui.py')
            self.adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.adapter)
        self.value = {'enabled': True, 'error': '', 'icons': [icon('one'), icon('two'), icon('hidden', True)]}
        self.client = SimpleNamespace(snapshot=lambda: self.value, icon_value=lambda _row: 77)
        self.adapter.client = self.client

    def test_width_counts_visible_and_overflow_slots_separately(self):
        self.assertEqual(self.adapter.logical_width(), 72)
        self.assertEqual(self.adapter.logical_width(maxicons=1), 48)
        self.assertEqual(self.adapter.logical_width(maxicons=0), 24)
        self.value['icons'] = []
        self.assertEqual(self.adapter.logical_width(), 0)
        self.value['enabled'] = False
        self.assertEqual(self.adapter.logical_width(), 0)

    def test_inline_rows_only_show_visible_with_one_overflow_button(self):
        layout = Layout()
        with mock.patch('builtins.open', side_effect=AssertionError('Draw cannot do I/O')):
            self.adapter.draw_icons(layout, self.context, maxicons=1)
        self.assertEqual([call[0] for call in layout.calls],
                         ['wm.blui_notification_action', 'wm.blui_notification_overflow'])
        self.assertEqual(layout.calls[0][2].key, 'one')
        self.assertEqual(layout.calls[0][1]['icon_value'], 77)

    def test_invalid_inline_limits_rejected(self):
        for count in (-1, 17, True, None):
            with self.assertRaises(ValueError):
                self.adapter.logical_width(count)

    def test_sync_is_event_boundary_only_and_retains_all_icons_for_overflow(self):
        self.assertTrue(self.adapter.sync(self.context))
        items = self.context.window_manager.blui_notification_settings.items
        self.assertEqual([item.key for item in items], ['one', 'two', 'hidden'])
        self.assertFalse(self.adapter.sync(self.context))
        # Main/RNA can be recreated at the same address; an empty new list must
        # be repopulated even when its identity and metadata signature match.
        items.clear()
        self.assertTrue(self.adapter.sync(self.context))
        self.assertEqual(len(items), 3)

    def test_action_poll_never_accepts_normal_user_window(self):
        for role in ('TASKBAR', 'TASK_CHOOSER'):
            context = SimpleNamespace(window=SimpleNamespace(blui_shell_role=role))
            self.assertTrue(self.adapter.WM_OT_blui_notification_action.poll(context))
        self.assertFalse(self.adapter.WM_OT_blui_notification_action.poll(
            SimpleNamespace(window=SimpleNamespace(blui_shell_role='NORMAL'))))
        self.assertFalse(self.adapter.WM_OT_blui_notification_action.poll(SimpleNamespace(window=None)))

    def test_tooltip_reads_current_ram_not_paths(self):
        self.assertEqual(self.adapter.WM_OT_blui_notification_action.description(
            None, SimpleNamespace(key='one')), 'one title')


if __name__ == '__main__':
    unittest.main(verbosity=2)
