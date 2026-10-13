# SPDX-License-Identifier: GPL-2.0-or-later
"""Mock-only DWM lifetime/identity checks. Never read real application windows."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import taskbar_previews as previews
from blui_desktop import taskbar_preview_layout as geometry


def task(handle='10', **extra):
    return {'handle': handle, 'pid': 100, 'thread_id': 101, 'process_started': '10000000',
            'window_class': 'AppWindow', 'title': 'Document', **extra}


class PreviewGeometryTests(unittest.TestCase):
    def test_layout_caps_four_and_stays_inside_monitor(self):
        for width in (32, 80, 320, 1920, 32768):
            for scale in (.5, 1, 1.5, 2, 8):
                value = geometry.preview_layout(20, width, scale=scale)
                self.assertLessEqual(value['count'], 4)
                self.assertLessEqual(value['width'], width)
                for slot in value['rects']:
                    self.assertGreaterEqual(slot[0], 0)
                    self.assertLessEqual(slot[2], value['width'])
                    self.assertLessEqual(slot[3], value['height'])

    def test_empty_layout_and_invalid_input(self):
        self.assertEqual(geometry.preview_layout(0, 500)['rects'], [])
        for count, width, scale in ((True, 500, 1), (-1, 500, 1), (257, 500, 1),
                                    (1, 0, 1), (1, 500, float('nan')), (1, 500, 0)):
            with self.assertRaises(ValueError):
                geometry.preview_layout(count, width, scale=scale)

    def test_fit_preserves_wide_and_tall_aspect(self):
        self.assertEqual(geometry.fit_rect((1600, 900), (10, 40, 250, 172)), (12, 40, 247, 172))
        self.assertEqual(geometry.fit_rect((900, 1600), (10, 40, 250, 172)), (93, 40, 167, 172))
        for size, rect in (((0, 1), (0, 0, 5, 5)), ((1, 1), (-1, 0, 5, 5)),
                           ((1, 1), (0, 0, 0, 5))):
            with self.assertRaises(ValueError):
                geometry.fit_rect(size, rect)


class DwmPreviewTests(unittest.TestCase):
    def setUp(self):
        self.user, self.dwm = mock.Mock(), mock.Mock()
        self.window = SimpleNamespace(blui_shell_role='TASK_CHOOSER', blui_native_handle='99',
                                      as_pointer=lambda: 1)
        self.owned = (999, 22, '44444', 'GHOST_WindowClass')
        self.identity = (100, 101, '10000000', 'AppWindow')
        self.user.GetAncestor.side_effect = lambda handle, _flags: handle
        self.user.IsWindowVisible.return_value = True
        self.user.IsIconic.return_value = False
        self.user.GetWindowDisplayAffinity.return_value = False
        def client(_handle, pointer):
            pointer._obj.right, pointer._obj.bottom = 2000, 1000
            return True
        self.user.GetClientRect.side_effect = client
        self.dwm.DwmGetWindowAttribute.return_value = 0
        def register(_destination, _source, pointer):
            pointer._obj.value = 1234 + self.dwm.DwmRegisterThumbnail.call_count
            return 0
        self.dwm.DwmRegisterThumbnail.side_effect = register
        def size(_token, pointer):
            pointer._obj.cx, pointer._obj.cy = 1600, 900
            return 0
        self.dwm.DwmQueryThumbnailSourceSize.side_effect = size
        self.dwm.DwmUpdateThumbnailProperties.return_value = 0
        self.dwm.DwmUnregisterThumbnail.return_value = 0
        patchers = (
            mock.patch.object(previews, '_user_api', return_value=self.user),
            mock.patch.object(previews, '_dwm_api', return_value=self.dwm),
            mock.patch.object(previews.window_placement, '_own', return_value=self.owned),
            mock.patch.object(previews.native_windows, '_identity', return_value=self.identity),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.controller = previews.PreviewController()
        self.addCleanup(self.controller.close)
        self.slots = [[10, 40, 250, 172]]

    def update(self, **extra):
        return self.controller.update(self.window, [task()], self.slots, **extra)

    def test_live_registration_updates_properties_and_no_duplicate_registration(self):
        result = self.update()
        self.assertEqual(result[0]['status'], 'LIVE')
        self.dwm.DwmRegisterThumbnail.assert_called_once()
        properties = self.dwm.DwmUpdateThumbnailProperties.call_args.args[1]._obj
        self.assertEqual(properties.flags, 0x1 | 0x4 | 0x8 | 0x10)
        self.assertTrue(properties.visible)
        self.assertFalse(properties.client_only)
        self.assertEqual(properties.opacity, 255)
        self.assertEqual([properties.destination.left, properties.destination.top,
                          properties.destination.right, properties.destination.bottom], result[0]['rect'])
        self.update()
        self.assertEqual(self.dwm.DwmRegisterThumbnail.call_count, 1)
        self.assertEqual(self.dwm.DwmUpdateThumbnailProperties.call_count, 1)
        # Draw snapshots cannot mutate controller state or perform API calls.
        snapshot = self.controller.snapshot()
        snapshot[0]['rect'][0] = 999
        self.assertNotEqual(self.controller.snapshot()[0]['rect'][0], 999)

    def test_minimized_and_protected_are_explicit_placeholders(self):
        self.user.IsIconic.return_value = True
        self.assertEqual(self.update()[0]['status'], 'MINIMIZED')
        self.dwm.DwmRegisterThumbnail.assert_not_called()
        self.user.IsIconic.return_value = False
        def affinity(_handle, pointer):
            pointer._obj.value = 0x11
            return True
        self.user.GetWindowDisplayAffinity.side_effect = affinity
        self.assertEqual(self.update()[0]['status'], 'PROTECTED')
        self.dwm.DwmRegisterThumbnail.assert_not_called()

    def test_cloaked_and_invisible_sources_are_not_registered(self):
        self.user.IsWindowVisible.return_value = False
        self.assertEqual(self.update()[0]['status'], 'UNAVAILABLE')
        self.user.IsWindowVisible.return_value = True
        def cloaked(_handle, _attribute, pointer, _size):
            pointer._obj.value = 1
            return 0
        self.dwm.DwmGetWindowAttribute.side_effect = cloaked
        self.assertEqual(self.update()[0]['status'], 'UNAVAILABLE')
        self.dwm.DwmRegisterThumbnail.assert_not_called()

    def test_excluded_shell_window_and_destination_are_never_sources(self):
        self.assertEqual(self.update(excluded=('10',))[0]['status'], 'EXCLUDED')
        result = self.controller.update(self.window, [task('99')], self.slots)
        self.assertEqual(result[0]['status'], 'EXCLUDED')
        self.dwm.DwmRegisterThumbnail.assert_not_called()

    def test_malformed_source_identity_is_rejected_without_native_registration(self):
        for extra in ({'handle': True}, {'pid': True}, {'thread_id': -1},
                      {'process_started': '0'}, {'window_class': 'App\x00Window'}):
            result = self.controller.update(self.window, [task(**extra)], self.slots)
            self.assertEqual(result[0]['status'], 'STALE')
        self.dwm.DwmRegisterThumbnail.assert_not_called()

    def test_source_pid_reuse_is_rejected(self):
        with mock.patch.object(previews.native_windows, '_identity', return_value=(100, 101, '20000', 'AppWindow')):
            self.assertEqual(self.update()[0]['status'], 'STALE')
        self.dwm.DwmRegisterThumbnail.assert_not_called()

    def test_identity_race_after_registration_unregisters_before_update(self):
        with mock.patch.object(previews.native_windows, '_identity',
                               side_effect=[self.identity, self.identity, None]):
            self.assertEqual(self.update()[0]['status'], 'STALE')
        self.dwm.DwmRegisterThumbnail.assert_called_once()
        self.dwm.DwmUpdateThumbnailProperties.assert_not_called()
        self.dwm.DwmUnregisterThumbnail.assert_called_once()

    def test_new_minimization_removes_old_live_relationship(self):
        self.update()
        self.user.IsIconic.return_value = True
        self.assertEqual(self.update()[0]['status'], 'MINIMIZED')
        self.dwm.DwmUnregisterThumbnail.assert_called_once()

    def test_final_source_identity_check_prevents_compositing_reused_hwnd(self):
        with mock.patch.object(previews.native_windows, '_identity',
                               side_effect=[self.identity, self.identity, self.identity, None]):
            self.assertEqual(self.update()[0]['status'], 'STALE')
        self.dwm.DwmUpdateThumbnailProperties.assert_not_called()
        self.dwm.DwmUnregisterThumbnail.assert_called_once()

    def test_active_controller_is_retained_until_close_or_process_cleanup(self):
        self.update()
        self.assertIn(self.controller, previews._controllers)
        previews.close_all()
        self.assertNotIn(self.controller, previews._controllers)
        self.dwm.DwmUnregisterThumbnail.assert_called_once()
        self.update()
        self.assertIn(self.controller, previews._controllers)

    def test_foreign_destination_or_taskbar_destination_rejected_and_cleanup(self):
        self.update()
        self.window.blui_shell_role = 'TASKBAR'
        with self.assertRaises(ValueError):
            self.update()
        self.dwm.DwmUnregisterThumbnail.assert_called_once()
        self.window.blui_shell_role = 'TASK_CHOOSER'
        with mock.patch.object(previews.window_placement, '_own', side_effect=RuntimeError('foreign PID')):
            with self.assertRaises(RuntimeError):
                self.update()

    def test_destination_change_mid_update_unlinks_old_thumbnail(self):
        with mock.patch.object(previews.window_placement, '_own',
                               side_effect=[self.owned, self.owned, (999, 33, '55555', 'GHOST_WindowClass')]):
            with self.assertRaises(RuntimeError):
                self.update()
        self.dwm.DwmUpdateThumbnailProperties.assert_not_called()
        self.dwm.DwmUnregisterThumbnail.assert_called_once()

    def test_registration_query_or_update_failure_is_unavailable_without_leak(self):
        for target in ('DwmRegisterThumbnail', 'DwmQueryThumbnailSourceSize', 'DwmUpdateThumbnailProperties'):
            self.controller.close()
            function = getattr(self.dwm, target)
            with mock.patch.object(self.dwm, target, return_value=-1):
                self.assertEqual(self.update()[0]['status'], 'UNAVAILABLE')
            self.assertEqual(self.controller._registrations, {})
            self.assertIs(getattr(self.dwm, target), function)

    def test_dwm_unavailable_returns_placeholder_and_no_registration(self):
        with mock.patch.object(previews, '_dwm_api', side_effect=OSError('no composition')):
            self.assertEqual(self.update()[0]['status'], 'UNAVAILABLE')
        self.dwm.DwmRegisterThumbnail.assert_not_called()

    def test_client_bounds_and_child_destination_rejected(self):
        for slots in ([[0, 0, 2500, 100]], [[-1, 0, 10, 10]], self.slots * 5):
            with self.assertRaises(ValueError):
                self.controller.update(self.window, [task()] * len(slots), slots)
        self.user.GetAncestor.return_value = 200
        self.user.GetAncestor.side_effect = None
        with self.assertRaises(RuntimeError):
            self.update()
        self.dwm.DwmRegisterThumbnail.assert_not_called()

    def test_close_and_clear_unregister_once_and_draw_is_empty(self):
        self.update()
        self.controller.close()
        self.controller.close()
        self.dwm.DwmUnregisterThumbnail.assert_called_once()
        self.assertEqual(self.controller.snapshot(), ())
        self.update()
        self.controller.update(self.window, [], [])
        self.assertEqual(self.dwm.DwmUnregisterThumbnail.call_count, 2)


if __name__ == '__main__':
    unittest.main()
