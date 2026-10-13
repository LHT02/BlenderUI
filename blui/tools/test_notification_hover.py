# SPDX-License-Identifier: GPL-2.0-or-later
"""Mock-only hover lifecycle, precise ownership, supported actions and passive source guards."""
from contextlib import nullcontext
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
import blui_desktop


def icon(key='hwnd:123:1', **kwargs):
    return dict({'key': key, 'handle': '123', 'uid': 1, 'guid': '', 'pid': 3, 'thread_id': 4,
        'process_started': '500', 'window_class': 'PrivateOwnedSource', 'callback': 0x401,
        'version': 4, 'tip': 'Native notification tooltip', 'cache_key': '',
        'actions': ['LEFT', 'RIGHT', 'DOUBLE', 'HOVER_ENTER', 'HOVER_LEAVE']}, **kwargs)


def window(pointer, handle, role):
    return SimpleNamespace(as_pointer=lambda: pointer, blui_native_handle=handle,
        blui_shell_role=role, screen=SimpleNamespace(areas=[SimpleNamespace(
            regions=[SimpleNamespace(type='WINDOW')], tag_redraw=mock.Mock())]))


class NotificationHoverTests(unittest.TestCase):
    def setUp(self):
        self.now, self.point, self.busy = 0., (150, 550), False
        self.bar = window(1, '100', 'TASKBAR')
        self.windows = [self.bar, window(2, '101', 'NORMAL'), window(3, '102', 'DESKTOP')]
        self.states, self.properties, self.closed = {}, {}, []
        self.snapshot = {'enabled': True, 'icons': [icon()]}
        self.context = SimpleNamespace(preferences=SimpleNamespace(view=SimpleNamespace(ui_scale=1)),
            temp_override=lambda **kwargs: nullcontext(), blui_shell_hover_button=SimpleNamespace(
                bl_rna=SimpleNamespace(identifier='WM_OT_blui_notification_action'), key='hwnd:123:1'))
        bpy = ModuleType('bpy')
        bpy.context = self.context
        types = ModuleType('bpy.types')
        types.Panel = object
        self.user = mock.Mock()
        self.user.GetWindowLongPtrW.return_value = 0x08000080
        self.user.GetPropW.side_effect = lambda handle, name: self.properties.get((handle, name), 0)
        def set_property(handle, name, value):
            self.properties[(handle, name)] = value
            return True
        self.user.SetPropW.side_effect = set_property
        self.identity = (99, 10, '20', 'GHOST_WindowClass')
        placement = SimpleNamespace(_api=lambda: self.user, _own=mock.Mock(return_value=self.identity))
        self.service = SimpleNamespace(window_placement=placement,
            role_windows=lambda role=None: [window for window in self.windows
                if window.blui_shell_role not in {'NORMAL', 'DESKTOP'} and
                (role is None or window.blui_shell_role == role)],
            device=lambda window: 'DISPLAY1',
            menu_state=lambda window: self.states.get(window.as_pointer(), {}),
            place_menu=mock.Mock())
        def create(context, role, width, height, **kwargs):
            self.assertTrue(kwargs['no_activate'])
            result = window(10 + len(self.windows), str(200 + len(self.windows)), role)
            self.windows.append(result)
            return result
        def close(target):
            self.closed.append(target)
            self.windows.remove(target)
            return True
        self.service.create = mock.Mock(side_effect=create)
        self.service.close_window = mock.Mock(side_effect=close)
        self.service.set_menu_state = lambda target, value: self.states.__setitem__(target.as_pointer(), value)
        self.client = SimpleNamespace(snapshot=lambda: self.snapshot, command=mock.Mock(return_value=True),
                                      icon_value=lambda row: 77)
        runtime = SimpleNamespace(shell_interaction_busy=lambda: self.busy,
            monitor_snapshot=lambda: {'monitors': [{'device': 'DISPLAY1', 'work': [0, 0, 1200, 500],
                                                   'dpi': [96, 96]}]})
        hover = ModuleType('blui_desktop.shell_hover')
        hover.inside = lambda target, point: target is self.bar and bool(point) and point[1] >= 500
        modules = mock.patch.dict(sys.modules, {'bpy': bpy, 'bpy.types': types,
                                               'blui_desktop.shell_hover': hover})
        modules.start()
        self.addCleanup(modules.stop)
        patches = [mock.patch.object(blui_desktop, key, value, create=True) for key, value in
                   (('runtime', runtime), ('taskbar_windows', self.service), ('notification_client', self.client))]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('blui_desktop._notification_hover_fixture',
            SOURCE / 'scripts/modules/blui_desktop/notification_hover.py')
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)
        self.adapter.iface = lambda text: text
        self.clock = mock.patch.object(self.adapter.time, 'monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def tick(self, now):
        self.now = now
        self.adapter.tick(lambda: self.point)

    def show(self):
        self.tick(0.)
        self.tick(.4)
        self.assertEqual(self.adapter.error(), '')
        return self.service.create.call_args

    def events(self):
        return [call.args[1] for call in self.client.command.call_args_list]

    def test_debounce_independent_passive_tip_and_enter_once(self):
        self.tick(0.)
        self.tick(.2)
        self.client.command.assert_not_called()
        self.service.create.assert_not_called()
        self.tick(.4)
        self.assertEqual(self.events(), ['HOVER_ENTER'])
        popup = self.windows[-1]
        self.assertEqual(self.states[popup.as_pointer()]['kind'], 'NOTIFICATION_TIP')
        self.assertEqual(popup.blui_shell_role, 'TASK_CHOOSER')
        for now in (.5, .6, 1.):
            self.tick(now)
        self.assertEqual(self.events(), ['HOVER_ENTER'])
        self.service.place_menu.assert_called_once()
        self.assertFalse(self.service.place_menu.call_args.kwargs['focus'])

    def test_leave_and_cancel_send_one_leave_close_only_own_tip(self):
        self.show()
        own = self.windows[-1]
        self.point = (0, 0)
        self.tick(.5)
        self.adapter.close()
        self.adapter.close()
        self.assertEqual(self.events(), ['HOVER_ENTER', 'HOVER_LEAVE'])
        self.assertEqual(self.closed, [own])
        self.assertEqual(self.windows, [self.bar, self.windows[1], self.windows[2]])

    def test_switch_between_icons_leaves_first_before_entering_second(self):
        self.show()
        self.snapshot['icons'].append(icon('hwnd:123:2', uid=2))
        self.context.blui_shell_hover_button.key = 'hwnd:123:2'
        self.tick(.5)
        self.tick(.9)
        self.assertEqual(self.events(), ['HOVER_ENTER', 'HOVER_LEAVE', 'HOVER_ENTER'])
        self.assertEqual(self.client.command.call_args.args[0], 'hwnd:123:2')

    def test_system_control_and_uia_tip_do_not_invent_hover_action(self):
        self.snapshot['icons'] = [icon(backend='UIA', callback=0, actions=['LEFT'])]
        self.show()
        self.client.command.assert_not_called()
        self.assertIn('Historical icon: default action only', self.adapter._lines)
        self.adapter.close()
        self.snapshot = {'enabled': True, 'icons': [], 'controls': [
            {'key': 'NETWORK', 'label': 'Network', 'actions': ['LEFT']}]}
        self.context.blui_shell_hover_button.key = 'system:NETWORK'
        self.tick(2.)
        self.tick(2.4)
        self.client.command.assert_not_called()
        self.assertEqual(self.adapter._lines, ('Network',))

    def test_removed_or_reused_callback_identity_never_receives_old_leave(self):
        self.show()
        self.snapshot['icons'][0]['process_started'] = '501'
        self.point = (0, 0)
        self.tick(.5)
        self.assertEqual(self.events(), ['HOVER_ENTER'])

    def test_other_menu_suppresses_tip_without_closing_it(self):
        self.show()
        own = self.windows[-1]
        menu = window(30, '500', 'TASK_CHOOSER')
        self.windows.append(menu)
        self.states[30] = {'kind': 'TASK_CONTEXT'}
        self.tick(.5)
        self.assertEqual(self.closed, [own])
        self.assertIn(menu, self.windows)
        self.assertEqual(self.events(), ['HOVER_ENTER', 'HOVER_LEAVE'])

    def test_start_or_preview_blocks_before_enter_or_window_creation(self):
        for role in ('STARTMENU', 'TASK_PREVIEW'):
            menu = window(30, '500', role)
            self.windows.append(menu)
            self.tick(0.)
            self.tick(.4)
            self.assertEqual(self.events(), [])
            self.service.create.assert_not_called()
            self.windows.remove(menu)

    def test_same_hwnd_popup_takeover_is_not_closed(self):
        self.show()
        popup = self.windows[-1]
        self.states[popup.as_pointer()] = {'kind': 'NOTIFICATION'}
        self.tick(.5)
        self.assertEqual(self.closed, [])
        self.assertIn(popup, self.windows)
        self.assertEqual(self.events(), ['HOVER_ENTER', 'HOVER_LEAVE'])

    def test_reused_native_property_token_is_not_closed(self):
        self.show()
        popup = self.windows[-1]
        self.properties[(int(popup.blui_native_handle), self.adapter.PROPERTY)] += 1
        self.point = (0, 0)
        self.tick(.5)
        self.assertEqual(self.closed, [])

    def test_source_bar_close_cleans_only_own_tip_and_callback(self):
        self.show()
        popup = self.windows[-1]
        self.adapter.closed(self.bar)
        self.assertEqual(self.closed, [popup])
        self.assertEqual(self.events(), ['HOVER_ENTER', 'HOVER_LEAVE'])

    def test_explicit_tooltip_close_suppresses_reopen_until_pointer_leaves(self):
        self.show()
        popup = self.windows[-1]
        self.adapter.closed(popup)
        self.windows.remove(popup)
        self.tick(.5)
        self.tick(1.)
        self.service.create.assert_called_once()
        self.point = (0, 0)
        self.tick(1.1)
        self.point = (150, 550)
        self.tick(1.2)
        self.tick(1.6)
        self.assertEqual(self.service.create.call_count, 2)

    def test_busy_mode_cleans_tip_and_never_sends_duplicate_leave(self):
        self.show()
        self.busy = True
        self.tick(.5)
        self.tick(.6)
        self.assertEqual(self.events(), ['HOVER_ENTER', 'HOVER_LEAVE'])

    def test_native_identity_change_never_closes_replacement(self):
        self.show()
        self.service.window_placement._own.return_value = (88, 10, '21', 'GHOST_WindowClass')
        self.point = (0, 0)
        self.tick(.5)
        self.assertEqual(self.closed, [])

    def test_draw_and_poll_only_read_prepared_ram(self):
        self.show()
        panel = self.adapter.BLUI_PT_notification_tip()
        panel.layout = SimpleNamespace(label=mock.Mock())
        context = SimpleNamespace(window=self.windows[-1])
        with (mock.patch.object(self.adapter, '_user', side_effect=AssertionError('No native draw API')),
              mock.patch.object(self.client, 'snapshot', side_effect=AssertionError('No snapshot in draw')),
              mock.patch('builtins.open', side_effect=AssertionError('No files in draw'))):
            self.assertTrue(panel.poll(context))
            panel.draw(context)
        panel.layout.label.assert_called_once()

    def test_text_wrapping_is_bounded_and_preserves_unicode_newline(self):
        self.assertEqual(self.adapter.tip_lines('中文名字\nclock', 8), ('中文名字', 'clock'))
        self.assertEqual(len(self.adapter.tip_lines('a' * 1000, 8)), 6)

    def test_coordinates_are_clamped_to_protocol_range(self):
        self.point = (100000, 100000)
        self.show()
        self.assertEqual(self.client.command.call_args.args[2:], (32767, 32767))


class PassiveNativeSourceGuards(unittest.TestCase):
    def test_no_activate_only_explicit_task_chooser_and_read_resets(self):
        text = (SOURCE / 'source/blender/windowmanager/intern/wm_window.c').read_text('utf-8')
        self.assertIn('win->blui_shell_role == WM_BLUI_SHELL_TASK_CHOOSER &&\n'
                      '                                 RNA_boolean_get(op->ptr, "no_activate")', text)
        self.assertIn('win->blui_shell_role == WM_BLUI_SHELL_TASK_CHOOSER && win->blui_shell_no_activate', text)
        reader = (SOURCE / 'source/blender/windowmanager/intern/wm.c').read_text('utf-8')
        self.assertIn('win->blui_shell_no_activate = 0;', reader)
        native = (SOURCE / 'intern/ghost/intern/GHOST_WindowWin32.cc').read_text('utf-8')
        self.assertIn('if (taskbar_window || passive_window)', native)
        # Passive does not install the AppBar subclass.
        self.assertIn('if (taskbar_window) {\n    m_bluiAppBarPreviousProc', native)


if __name__ == '__main__':
    unittest.main(verbosity=2)
