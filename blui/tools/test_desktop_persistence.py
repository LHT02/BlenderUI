# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolated multi-monitor desktop services; no bpy, user-window movement or real files."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts' / 'modules'))
from blui_desktop import autosave, boards, model, monitors
from blui_explorer import mailbox


def collection():
    result = boards.new_collection('主屏', {'version': 1, 'directory': '', 'nodes': [
        {'kind': model.FILE, 'path': 'C:\\fixture\\图标.lnk', 'name': '快捷方式',
         'location': [10, 20], 'folder': False}]})
    secondary = boards.new_board('副屏')
    result['boards'].append(secondary)
    result['boards'][0]['monitor'] = r'\\.\DISPLAY1'
    secondary['monitor'] = r'\\.\DISPLAY2'
    return result


def displays(second=True):
    rows = [{'device': r'\\.\DISPLAY1', 'rect': [0, 0, 1920, 1080],
             'work': [0, 0, 1920, 1040], 'dpi': [96, 96], 'primary': True}]
    if second:
        rows.append({'device': r'\\.\DISPLAY2', 'rect': [-2560, -200, 0, 1240],
                     'work': [-2560, -200, 0, 1200], 'dpi': [144, 144], 'primary': False})
    return {'coordinate_space': 'physical', 'monitors': rows}


class FakeJob:
    def __init__(self, snapshot, path):
        self.value = {'id': snapshot['id'], 'revision': snapshot['revision'], 'path': path}
        self.ready = False
        self.closed = False
        self.error = None

    def done(self):
        return self.ready

    def result(self):
        if self.error:
            raise RuntimeError(self.error)
        return self.value

    def close(self):
        self.closed = True


class PersistenceTests(unittest.TestCase):
    def test_complete_snapshot_and_first_save_backup_recover_all_screens(self):
        snapshot = collection()
        with tempfile.TemporaryDirectory(prefix='blui_boards_test_') as directory:
            target = Path(directory) / 'desktop.json'
            receipt = boards.save(target, snapshot)
            self.assertEqual(receipt['revision'], 0)
            self.assertFalse(target.read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertEqual(boards.load(target), boards.validate(snapshot))
            target.write_bytes(b'{half written')
            restored = boards.load(target)
            self.assertEqual(len(restored['boards']), 2)
            self.assertEqual(restored['boards'][0]['layout']['nodes'][0]['path'],
                             snapshot['boards'][0]['layout']['nodes'][0]['path'])
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_out_of_order_save_and_per_canvas_revision_never_roll_back(self):
        old = collection()
        newer = deepcopy(old)
        newer['revision'] = 5
        newer['boards'][0]['revision'] = 4
        with tempfile.TemporaryDirectory(prefix='blui_boards_order_') as directory:
            target = Path(directory) / 'desktop.json'
            boards.save(target, old)
            boards.save(target, newer)
            with self.assertRaisesRegex(ValueError, 'older desktop'):
                boards.save(target, old)
            wrong_board = deepcopy(newer)
            wrong_board['revision'] = 6
            wrong_board['boards'][0]['revision'] = 3
            with self.assertRaisesRegex(ValueError, 'older canvas'):
                boards.save(target, wrong_board)
            conflict = deepcopy(newer)
            conflict['boards'][0]['name'] = 'different'
            with self.assertRaisesRegex(ValueError, 'same revision'):
                boards.save(target, conflict)
            with self.assertRaisesRegex(ValueError, 'different desktop'):
                boards.save(target, collection())
            self.assertEqual(boards.load(target)['revision'], 5)

    def test_corrupt_current_does_not_poison_the_last_valid_backup(self):
        first = collection()
        second = deepcopy(first)
        second['revision'] = second['boards'][0]['revision'] = 1
        third = deepcopy(second)
        third['revision'] = third['boards'][0]['revision'] = 2
        with tempfile.TemporaryDirectory(prefix='blui_boards_corrupt_') as directory:
            target = Path(directory) / 'desktop.json'
            boards.save(target, first)
            boards.save(target, second)
            target.write_bytes(b'\xff not utf8')
            boards.save(target, third)
            self.assertEqual(boards.load(target)['revision'], 2)
            self.assertEqual(boards.load(target.with_suffix('.bak'))['revision'], 0)

    def test_recovery_picks_highest_complete_revision_not_mtime(self):
        snapshot = collection()
        newer = deepcopy(snapshot)
        newer['revision'] = 9
        with tempfile.TemporaryDirectory(prefix='blui_boards_recovery_') as directory:
            target = Path(directory) / 'desktop.json'
            target.write_bytes(boards.encoded(snapshot))
            target.with_suffix('.bak').write_bytes(boards.encoded(newer))
            self.assertEqual(boards.load(target)['revision'], 9)

    def test_idempotent_retry_repairs_backup_if_first_backup_publish_was_interrupted(self):
        snapshot = collection()
        with tempfile.TemporaryDirectory(prefix='blui_boards_first_backup_') as directory:
            target = Path(directory) / 'desktop.json'
            publish = model._publish
            def fail_backup(path, data):
                if path == target.with_suffix('.bak'):
                    raise OSError('simulated first backup interruption')
                return publish(path, data)
            with mock.patch.object(model, '_publish', side_effect=fail_backup):
                with self.assertRaises(OSError):
                    boards.save(target, snapshot)
            self.assertTrue(target.exists())
            self.assertFalse(target.with_suffix('.bak').exists())
            boards.save(target, snapshot)
            target.unlink()
            self.assertEqual(boards.load(target), boards.validate(snapshot))

    def test_save_failure_leaves_a_valid_complete_snapshot_and_no_temporary_file(self):
        snapshot = collection()
        with tempfile.TemporaryDirectory(prefix='blui_boards_crash_') as directory:
            target = Path(directory) / 'desktop.json'
            boards.save(target, snapshot)
            newer = deepcopy(snapshot)
            newer['revision'] = 1
            replace = model.os.replace
            def fail_current(source, destination):
                if Path(destination) == target:
                    raise OSError('simulated interrupted write')
                return replace(source, destination)
            with mock.patch.object(model.os, 'replace', side_effect=fail_current):
                with self.assertRaises(OSError):
                    boards.save(target, newer)
            self.assertEqual(boards.load(target), boards.validate(snapshot))
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_transfer_is_reference_only_atomic_relative_and_epoch_checked(self):
        original = collection()
        source, target = original['boards']
        key = source['layout']['nodes'][0]['id']
        prepared = boards.prepare_transfer(original, source['id'], target['id'], [key],
                                           origin=(200, -300), epoch=7)
        with mock.patch.object(model.os, 'scandir', side_effect=AssertionError('No filesystem')):
            result = boards.commit_transfer(original, prepared, epoch=7)
        self.assertEqual(len(original['boards'][0]['layout']['nodes']), 1)
        self.assertEqual(len(result['boards'][0]['layout']['nodes']), 0)
        copied = result['boards'][1]['layout']['nodes'][0]
        self.assertEqual(copied['id'], key)
        self.assertEqual(copied['path'], source['layout']['nodes'][0]['path'])
        self.assertEqual(copied['location'], [200, -300])
        with self.assertRaisesRegex(ValueError, 'expired'):
            boards.commit_transfer(original, prepared, epoch=8)
        changed = deepcopy(original)
        changed['boards'][0]['layout']['nodes'][0]['location'][0] += 1
        with self.assertRaisesRegex(ValueError, 'changed during'):
            boards.commit_transfer(changed, prepared, epoch=7)
        with self.assertRaisesRegex(ValueError, 'changed during'):
            boards.commit_transfer(result, prepared, epoch=7)

    def test_ctrl_transfer_copies_references_with_fresh_ids_without_disk_copy(self):
        original = collection()
        source, target = original['boards']
        key = source['layout']['nodes'][0]['id']
        prepared = boards.prepare_transfer(original, source['id'], target['id'], [key], copy=True)
        result = boards.commit_transfer(original, prepared)
        self.assertEqual(result['boards'][0], source)
        row = result['boards'][1]['layout']['nodes'][0]
        self.assertNotEqual(row['id'], key)
        self.assertEqual(row['path'], source['layout']['nodes'][0]['path'])

    def test_transfer_rejects_invalid_ids_and_capacity_without_source_loss(self):
        original = collection()
        source, target = original['boards']
        for keys in ([{}], [None], [], ['bad']):
            with self.assertRaises(ValueError):
                boards.prepare_transfer(original, source['id'], target['id'], keys)
        prepared = boards.prepare_transfer(original, source['id'], target['id'],
                                           [source['layout']['nodes'][0]['id']])
        for field in ('source', 'target'):
            malformed = deepcopy(prepared)
            malformed[field] = {}
            with self.assertRaises(ValueError):
                boards.commit_transfer(original, malformed)
        self.assertEqual(len(original['boards'][0]['layout']['nodes']), 1)

    def test_removed_display_keeps_layout_and_reconnected_display_rebinds(self):
        snapshot = collection()
        before = boards.fingerprint(snapshot)
        detached = boards.display_bindings(snapshot, displays(False))
        self.assertEqual(detached['detached'], [snapshot['boards'][1]['id']])
        restored = boards.display_bindings(snapshot, displays(True))
        self.assertFalse(restored['detached'])
        self.assertEqual(restored['attached'][0]['boards'], [snapshot['boards'][0]['id']])
        self.assertEqual(boards.fingerprint(snapshot), before)

    def test_monitor_suggestions_handle_negative_origin_dpi_and_no_displays(self):
        original = [-2400, -100, -1600, 600]
        self.assertFalse(monitors.placement(original, displays())['changed'])
        suggested = monitors.placement(original, displays(False), preferred=r'\\.\DISPLAY2',
                                       old_dpi=[144, 144])
        self.assertEqual(suggested['rect'], [0, 0, 533, 467])
        self.assertEqual(suggested['device'], r'\\.\DISPLAY1')
        self.assertIsNone(monitors.placement(original, {'coordinate_space': 'physical', 'monitors': []}))
        huge = monitors.placement([5000, 5000, 12000, 15000], displays(False))
        self.assertEqual(huge['rect'], [0, 0, 1920, 1040])
        self.assertNotEqual(monitors.topology_key(displays()), monitors.topology_key(displays(False)))

    def test_monitor_schema_rejects_malformed_topology(self):
        for field, value in (('dpi', [True, 96]), ('work', [0, 0, 5000, 5000]),
                             ('device', ''), ('primary', 1), ('rect', [0, 0, 0, 1080])):
            malformed = displays(False)
            malformed['monitors'][0][field] = value
            with self.assertRaises(ValueError):
                monitors.validate(malformed)

    def test_scheduler_default_interval_inflight_newer_dirty_and_force(self):
        jobs, clock = [], [100.0]
        def factory(action, path, payload):
            self.assertEqual(action, 'board_save')
            job = FakeJob(payload, path)
            jobs.append(job)
            return job
        scheduler = autosave.Scheduler(factory, clock=lambda: clock[0])
        original = collection()
        scheduler.observe('memory-only.json', original, epoch=2)
        clock[0] += 29
        scheduler.tick()
        self.assertFalse(jobs)
        clock[0] += 1
        scheduler.tick()
        self.assertEqual(len(jobs), 1)
        newer = deepcopy(original)
        newer['revision'] = newer['boards'][0]['revision'] = 1
        scheduler.observe('memory-only.json', newer, epoch=2)
        jobs[0].ready = True
        self.assertEqual(scheduler.tick(), {'saved': True, 'revision': 0})
        self.assertTrue(scheduler.dirty)
        scheduler.tick(force=True)
        self.assertEqual(len(jobs), 2)
        jobs[1].ready = True
        scheduler.tick()
        self.assertFalse(scheduler.dirty)
        self.assertEqual(scheduler.saved_revision, 1)

    def test_scheduler_retry_cancellation_and_ack_validation(self):
        jobs, clock = [], [10.0]
        def factory(action, path, payload):
            job = FakeJob(payload, path)
            jobs.append(job)
            return job
        scheduler = autosave.Scheduler(factory, interval=5, clock=lambda: clock[0])
        scheduler.observe('memory.json', collection(), epoch=1)
        scheduler.tick(force=True)
        jobs[0].ready, jobs[0].error = True, 'simulated crash'
        self.assertFalse(scheduler.tick()['saved'])
        self.assertTrue(scheduler.dirty)
        scheduler.tick()
        self.assertEqual(len(jobs), 1)
        clock[0] += 2
        scheduler.tick()
        self.assertEqual(len(jobs), 2)
        jobs[1].ready = True
        jobs[1].value['revision'] = 999
        self.assertFalse(scheduler.tick()['saved'])
        scheduler.tick(force=True)
        scheduler.reset(epoch=2)
        self.assertTrue(jobs[-1].closed)
        self.assertFalse(scheduler.dirty)

    def test_scheduler_has_no_filesystem_or_native_calls(self):
        original = collection()
        job = FakeJob(original, 'memory.json')
        with mock.patch.object(model.os, 'stat', side_effect=AssertionError('Main thread filesystem')), \
             mock.patch.object(monitors, 'snapshot', side_effect=AssertionError('Main thread native query')):
            scheduler = autosave.Scheduler(lambda *args: job)
            scheduler.observe('memory.json', original)
            scheduler.tick(force=True)
            job.ready = True
            scheduler.tick()
            self.assertFalse(scheduler.dirty)

    def test_real_worker_allowlist_saves_loads_and_reads_monitors(self):
        with tempfile.TemporaryDirectory(prefix='blui_boards_worker_') as directory:
            target = str(Path(directory) / 'desktop.json')
            for action, args in (('board_save', [target, collection()]), ('board_load', [target]),
                                 ('monitors', []), ('unapproved', [])):
                mailbox.publish(directory, 'request.json', {'action': action, 'args': args})
                result = subprocess.run([sys.executable, '-I', '-B',
                    str(SOURCE / 'scripts/modules/blui_desktop/worker.py'), directory],
                    timeout=8, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.assertEqual(result.returncode, 0, result.stderr)
                reply = mailbox.take(directory, 'result.json')
                self.assertEqual(reply['ok'], action != 'unapproved', reply)
                if action == 'monitors':
                    monitors.validate(reply['value'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
