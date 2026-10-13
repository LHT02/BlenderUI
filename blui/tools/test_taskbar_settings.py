# SPDX-License-Identifier: GPL-2.0-or-later
"""Taskbar preference schema, atomic recovery and nonblocking-job adapter checks."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'modules'))
from blui_desktop import taskbar_settings as settings


class SchemaTests(unittest.TestCase):
    def test_default_and_large_icon_height_clearance(self):
        self.assertEqual(settings.defaults()['height'], 56)
        self.assertEqual(settings.changed(settings.defaults(), height=32, icon_size=64),
                         {'version': 1, 'revision': 1, 'height': 80, 'icon_size': 64})
        self.assertEqual(settings.changed(settings.defaults()), settings.defaults())

    def test_malformed_bounds_unknown_keys_and_boolean_rejected(self):
        for changes in ({'height': True}, {'height': 161}, {'height': 31}, {'icon_size': 65},
                        {'icon_size': 15}, {'version': 2}, {'revision': -1}, {'extra': 1}):
            with self.assertRaises(ValueError):
                settings.validate({**settings.defaults(), **changes})
        with self.assertRaises(ValueError):
            settings.validate({'height': 56, 'icon_size': 32})

    def test_atomic_utf8_and_valid_backup_recovery(self):
        with tempfile.TemporaryDirectory(prefix='blui-taskbar-settings-') as directory:
            first = settings.changed(settings.defaults(), height=64)
            second = settings.changed(first, height=80)
            self.assertTrue(settings.save(directory, first))
            self.assertTrue(settings.save(directory, second))
            target = Path(directory) / 'taskbar-settings.json'
            self.assertFalse(target.read_bytes().startswith(b'\xef\xbb\xbf'))
            self.assertEqual(settings.load(directory), second)
            with target.open('wb') as output:
                output.write(b'broken-json')
            self.assertEqual(settings.load(directory), first)
            repaired = settings.changed(first, icon_size=48)
            settings.save(directory, repaired)
            self.assertEqual(settings.load(directory), repaired)
            self.assertEqual(json.loads(target.with_suffix('.bak').read_text('utf-8')), first)

    def test_old_or_conflicting_revision_does_not_overwrite(self):
        with tempfile.TemporaryDirectory(prefix='blui-taskbar-settings-') as directory:
            first = settings.changed(settings.defaults(), height=64)
            settings.save(directory, first)
            for stale in (settings.defaults(), {**first, 'height': 80}):
                with self.assertRaises(ValueError):
                    settings.save(directory, stale)
            self.assertEqual(settings.load(directory), first)

    def test_invalid_directory_rejected(self):
        for directory in ('', 'relative', 'C:\x00bad', True):
            with self.assertRaises(ValueError):
                settings.load(directory)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.state = {key: getattr(settings, key) for key in
                      ('_current', '_directory', '_loaded', '_dirty', '_job', '_action', '_submitted', '_retry', '_error')}
        patcher = mock.patch.multiple(settings, _current=settings.defaults(), _directory='', _loaded=False,
                                     _dirty=False, _job=None, _action='', _submitted=None, _retry=0., _error='')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.jobs = []
        def factory(action, *args, **kwargs):
            job = mock.Mock()
            job.done.return_value = False
            job.reply = None
            job.action, job.args = action, args
            self.jobs.append(job)
            return job
        self.factory = factory
        self.directory = str(Path.cwd())

    def tick(self, now=0):
        return settings.service_tick(self.directory, clock=lambda: now, job_factory=self.factory)

    def complete(self, value, ok=True):
        self.jobs[-1].done.return_value = True
        self.jobs[-1].reply = {'ok': ok, 'value': value, 'error': 'conflict'}

    def test_configure_is_ram_only_and_load_does_not_lose_user_edit(self):
        with mock.patch.object(settings, '_path', side_effect=AssertionError('draw did I/O')):
            settings.configure(icon_size=48)
            self.assertEqual(settings.values()['height'], 64)
        self.tick()
        self.assertEqual(self.jobs[-1].action, 'taskbar_settings_load')
        self.complete({**settings.defaults(), 'revision': 20})
        self.tick()
        self.assertEqual(settings.values()['revision'], 21)
        self.assertEqual(settings.values()['icon_size'], 48)
        self.assertEqual(self.jobs[-1].action, 'taskbar_settings_save')

    def test_edits_during_save_are_coalesced_not_lost(self):
        self.tick()
        self.complete(settings.defaults())
        self.tick()
        settings.configure(height=64)
        self.tick()
        first = self.jobs[-1]
        settings.configure(height=80)
        self.complete(True)
        self.tick()
        self.assertEqual(self.jobs[-1].args[1]['height'], 80)
        self.assertIsNot(self.jobs[-1], first)
        self.complete(True)
        self.tick()
        self.assertFalse(settings._dirty)

    def test_failure_retries_after_cooldown_and_shutdown_does_not_block(self):
        self.tick()
        self.complete(None, ok=False)
        self.tick()
        self.assertEqual(settings.error(), 'conflict')
        self.tick(2)
        self.assertEqual(len(self.jobs), 1)
        self.tick(3)
        self.assertEqual(len(self.jobs), 2)
        settings.shutdown()
        self.jobs[-1].close.assert_called_once()
        self.jobs[-1].wait.assert_not_called()


if __name__ == '__main__':
    unittest.main()
