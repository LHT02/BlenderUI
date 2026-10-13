# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure host integration state-machine tests; no bpy, threads, helper or Windows changes."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop.desktop_service import Service


def displays(two=True):
    rows = [{'device': 'DISPLAY1', 'rect': [0, 0, 1920, 1080], 'work': [0, 0, 1920, 1040],
             'dpi': [96, 96], 'primary': True}]
    if two:
        rows.append({'device': 'DISPLAY2', 'rect': [-1920, 0, 0, 1080], 'work': [-1920, 0, 0, 1040],
                     'dpi': [144, 144], 'primary': False})
    return {'coordinate_space': 'physical', 'monitors': rows}


class Host:
    def __init__(self):
        self.state = {'enabled': False, 'attached_count': 0, 'handles': [], 'pending_restore': False,
                      'need_rebind': False, 'error': '', 'state': 'Windows Desktop Unchanged',
                      'completed_serial': 0}
        self.calls = []
        self.serial = 0

    def snapshot(self):
        return deepcopy(self.state)

    def tick(self):
        self.calls.append(('heartbeat',))
        return self.snapshot()

    def start(self, directory):
        self.calls.append(('start', directory))

    def restore(self):
        self.serial += 1
        self.calls.append(('restore', self.serial))
        return self.serial

    def reconcile(self, rows):
        self.serial += 1
        self.calls.append(('reconcile', self.serial, deepcopy(rows)))
        return self.serial

    def ack(self, *, enabled=False, handles=(), pending=False, error=''):
        self.state.update(enabled=enabled, attached_count=len(handles), handles=list(handles),
                          pending_restore=pending, error=error, completed_serial=self.serial,
                          need_rebind=False,
                          state='BLUI Desktop Connected' if enabled else 'Windows Desktop Restored')

    def close(self):
        self.calls.append(('close',))


class Adapter:
    def __init__(self):
        self.calls, self.live = [], {}
        self.is_busy, self.is_ready = False, True
        self.counter = 100
        self.fail_configure = False
        self.deferred_scan = ''
        self.scan_done = True
        self.save_done = True

    def directory(self):
        return 'D:/OWN_TEST_ONLY'

    def alive(self, token):
        return token in self.live

    def busy(self):
        return self.is_busy

    def ready(self):
        self.calls.append(('profile-ready',))
        return self.is_ready

    def refresh_monitors(self):
        self.calls.append(('refresh-monitors',))

    def create(self, display):
        self.counter += 1
        token = (self.counter, str(self.counter + 10000))
        self.live[token] = display['device']
        self.calls.append(('create', token, display['device']))
        return token

    def configure(self, token, display):
        self.calls.append(('configure', token, display['device']))
        if self.fail_configure:
            raise RuntimeError('simulated job/tree setup failure')
        return self.deferred_scan

    def close(self, token):
        self.calls.append(('close', token))
        self.live.pop(token, None)

    def scan(self, board):
        self.calls.append(('scan', board))
        return self.scan_done

    def finish_save(self):
        self.calls.append(('save-tail',))
        return self.save_done, ''


class DesktopServiceTests(unittest.TestCase):
    def setUp(self):
        self.host, self.adapter = Host(), Adapter()
        self.service = Service(self.adapter, self.host)
        self.first = displays()

    def connected(self):
        self.service.tick(self.first)
        self.service.enable()
        self.host.ack()
        self.fresh = deepcopy(self.first)
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'CONNECTING')
        self.host.ack(enabled=True, handles=[token[1] for token in self.service.owned])
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'CONNECTED')

    def test_default_does_not_start_helpers_or_change_windows(self):
        self.service.tick(self.first)
        self.assertFalse(self.service.desired)
        self.assertFalse(self.service.needs_service())
        self.assertEqual(self.host.calls, [('heartbeat',)])  # RAM only, no start/restore/native action.
        self.assertEqual(self.adapter.calls, [])

    def test_enable_waits_for_actual_restore_ack_and_fresh_snapshot(self):
        self.service.tick(self.first)
        self.service.enable()
        self.service.tick(self.first)
        self.assertEqual(self.service.phase, 'RESTORING')
        self.assertEqual(self.adapter.live, {})
        self.host.ack()
        self.service.tick(self.first)
        self.assertEqual(self.service.phase, 'BUILDING')
        self.assertEqual(self.adapter.live, {})
        self.service.tick(deepcopy(self.first))
        self.assertEqual(len(self.adapter.live), 2)
        request = next(call for call in self.host.calls if call[0] == 'reconcile')
        self.assertEqual({row['device'] for row in request[2]}, {'DISPLAY1', 'DISPLAY2'})
        self.assertEqual(next(row for row in request[2] if row['device'] == 'DISPLAY2')['rect'][0], -1920)

    def test_profile_restore_finishes_before_new_canvases(self):
        self.adapter.is_ready = False
        self.service.enable()
        self.host.ack()
        self.service.tick(self.first)
        self.assertEqual(self.adapter.live, {})
        self.adapter.is_ready = True
        self.service.tick(self.first)
        self.assertEqual(len(self.adapter.live), 2)

    def test_disable_never_closes_sources_on_initial_empty_status(self):
        self.connected()
        owned = dict(self.service.owned)
        self.service.restore()
        self.host.state.update(enabled=False, handles=[], attached_count=0, pending_restore=False)
        self.service.tick(self.fresh)
        self.assertEqual(self.service.owned, owned)
        self.assertFalse(any(call[0] == 'close' for call in self.adapter.calls))
        self.host.ack(pending=True)
        self.service.tick(self.fresh)
        self.assertEqual(self.service.owned, owned)
        self.host.ack()
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'IDLE')
        self.assertEqual(self.adapter.live, {})

    def test_node_modal_blocks_create_close_but_not_heartbeat_or_restore(self):
        self.connected()
        self.adapter.is_busy = True
        self.service.restore()
        self.host.ack()
        before = len(self.host.calls)
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'RESTORING')
        self.assertTrue(self.service.owned)
        self.assertGreater(len(self.host.calls), before)
        self.adapter.is_busy = False
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'IDLE')

    def test_undo_detaches_without_closing_canvas_or_restarting_by_itself(self):
        self.connected()
        owned = dict(self.service.owned)
        self.service.cancel_pending()
        self.assertFalse(self.service.desired)
        self.host.ack()
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'DETACHED')
        self.assertEqual(self.service.owned, owned)
        self.assertFalse(any(call[0] == 'close' for call in self.adapter.calls))

    def test_work_area_change_restores_and_waits_then_reuses_own_windows(self):
        self.connected()
        owned = dict(self.service.owned)
        changed = deepcopy(self.fresh)
        changed['monitors'][0]['work'][3] = 1000
        self.service.tick(changed)
        self.assertEqual(self.service.phase, 'RESTORING')
        self.host.ack()
        self.service.tick(changed)
        self.assertEqual(self.service.phase, 'BUILDING')
        fresh = deepcopy(changed)
        self.service.tick(fresh)
        self.assertEqual(self.service.owned, owned)
        self.assertEqual(sum(call[0] == 'create' for call in self.adapter.calls), 2)
        self.assertEqual(self.service.phase, 'CONNECTING')

    def test_monitor_removed_closes_only_own_removed_surface_after_restore(self):
        self.connected()
        removed = next(token for token, device in self.service.owned.items() if device == 'DISPLAY2')
        changed = displays(False)
        self.service.tick(changed)
        self.assertIn(removed, self.adapter.live)
        self.host.ack()
        self.service.tick(deepcopy(changed))
        self.assertNotIn(removed, self.adapter.live)
        self.assertEqual(list(self.service.owned.values()), ['DISPLAY1'])

    def test_native_parent_loss_replaces_only_missing_token(self):
        self.connected()
        old = next(token for token, device in self.service.owned.items() if device == 'DISPLAY2')
        surviving = next(token for token, device in self.service.owned.items() if device == 'DISPLAY1')
        self.adapter.live.pop(old)
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'RESTORING')
        self.host.ack()
        self.service.tick(deepcopy(self.fresh))
        self.assertIn(surviving, self.service.owned)
        self.assertNotIn(old, self.service.owned)
        self.assertEqual(len(self.service.owned), 2)

    def test_need_rebind_from_helper_forces_fresh_monitor_job(self):
        self.connected()
        self.host.state['need_rebind'] = True
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'RESTORING')
        self.assertEqual(self.adapter.calls[-1], ('refresh-monitors',))

    def test_setup_failure_tracks_source_then_waits_for_restore_before_closing(self):
        self.adapter.fail_configure = True
        self.service.enable()
        self.host.ack()
        self.service.tick(self.first)
        self.assertEqual(self.service.phase, 'RESTORING')
        self.assertEqual(len(self.service.owned), 1)
        self.assertFalse(self.service.desired)
        self.assertFalse(any(call[0] == 'close' for call in self.adapter.calls))
        self.host.ack()
        self.service.tick(self.first)
        self.assertFalse(self.service.owned)

    def test_dpi_fail_closed_error_restores_before_source_cleanup(self):
        self.service.enable()
        self.host.ack()
        self.service.tick(self.first)
        self.host.ack(error='Desktop and BLUI DPI awareness differ; Windows desktop is preserved')
        self.service.tick(self.first)
        self.assertEqual(self.service.phase, 'RESTORING')
        self.assertFalse(self.service.desired)
        self.assertTrue(self.service.owned)
        self.host.ack()
        self.service.tick(self.first)
        self.assertFalse(self.service.owned)
        self.assertIn('DPI', self.service.snapshot()['error'])

    def test_load_shutdown_then_shared_cancel_never_restarts_helper(self):
        self.connected()
        self.service.shutdown()
        calls = list(self.host.calls)
        self.service.cancel_pending()
        self.assertEqual(self.host.calls, calls)
        self.assertFalse(self.service.desired)
        self.assertFalse(self.service.owned)
        self.assertEqual(self.service.phase, 'CLOSING')
        self.host.ack()
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'IDLE')

    def test_deferred_scan_retries_bounded_admission_without_new_windows(self):
        self.adapter.deferred_scan = 'board-one'
        self.adapter.scan_done = False
        self.connected()
        self.assertEqual(self.service.deferred_scans, {'board-one'})
        self.adapter.scan_done = True
        self.service.tick(self.fresh)
        self.assertEqual(self.service.deferred_scans, set())
        self.assertEqual(sum(call[0] == 'create' for call in self.adapter.calls), 2)

    def test_final_layout_save_tail_keeps_timer_but_windows_already_restored(self):
        self.connected()
        self.adapter.save_done = False
        self.service.restore()
        self.host.ack()
        self.service.tick(self.fresh)
        self.assertFalse(self.service.owned)
        self.assertEqual(self.service.phase, 'SAVING')
        self.assertTrue(self.service.needs_service())
        self.adapter.save_done = True
        self.service.tick(self.fresh)
        self.assertEqual(self.service.phase, 'IDLE')


if __name__ == '__main__':
    unittest.main()
