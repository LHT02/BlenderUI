# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure-memory autosave scheduling; injected jobs do all filesystem work off-thread."""
from copy import deepcopy
import math
import os
import time

from . import boards


class Scheduler:
    """One in-flight snapshot, bounded retries, and epoch-safe acknowledgements.

    ``job_factory('board_save', path, snapshot)`` must return a nonblocking job
    with memory-only ``done/result/close`` methods. This module never uses bpy,
    filesystem functions, native Windows APIs, or a timer-owned worker thread.
    """
    def __init__(self, job_factory, *, interval=30.0, clock=time.monotonic):
        self.job_factory, self.clock = job_factory, clock
        self.set_interval(interval)
        self.epoch = 0
        self.path = ''
        self.pending = None
        self.pending_hash = ''
        self.saved_hash = ''
        self.saved_revision = -1
        self.job = None
        self.inflight = None
        self.next_due = self.clock() + self.interval
        self.failures = 0
        self.error = ''

    def set_interval(self, interval):
        if type(interval) not in (int, float) or not math.isfinite(interval) or not 5 <= interval <= 3600:
            raise ValueError('Autosave interval must be between 5 and 3600 seconds')
        self.interval = float(interval)

    @property
    def dirty(self):
        return self.pending is not None and self.pending_hash != self.saved_hash

    def observe(self, path, snapshot, *, epoch=0, already_saved=False):
        if not isinstance(path, str) or not path or len(path) > 32768 or '\x00' in path:
            raise ValueError('Invalid desktop snapshot path')
        if type(epoch) is not int or epoch < 0:
            raise ValueError('Invalid desktop autosave epoch')
        path = os.path.normpath(path)  # String-only normalization, no filesystem access.
        clean = boards.validate(snapshot)
        digest = boards.fingerprint(clean)
        if self.path and (path != self.path or epoch != self.epoch or
                          (self.pending and clean['id'] != self.pending['id'])):
            self.reset(epoch=epoch)
        if self.pending and clean['revision'] < self.pending['revision']:
            raise ValueError('Autosave cannot observe an older desktop revision')
        if self.pending and clean['revision'] == self.pending['revision'] and digest != self.pending_hash:
            raise ValueError('Desktop changed without incrementing its revision')
        self.path, self.epoch = path, epoch
        self.pending, self.pending_hash = clean, digest
        if already_saved:
            self.saved_hash, self.saved_revision = digest, clean['revision']

    def reset(self, *, epoch=0):
        if self.job:
            self.job.close()
        self.job, self.inflight = None, None
        self.path, self.pending = '', None
        self.pending_hash = self.saved_hash = ''
        self.saved_revision = -1
        self.epoch = epoch
        self.failures, self.error = 0, ''
        self.next_due = self.clock() + self.interval

    def tick(self, *, now=None, force=False):
        now = self.clock() if now is None else now
        event = None
        if self.job and self.job.done():
            job, inflight = self.job, self.inflight
            self.job = self.inflight = None
            try:
                value = job.result()
                if (not isinstance(value, dict) or value.get('id') != inflight['id'] or
                        value.get('revision') != inflight['revision'] or value.get('path') != inflight['path']):
                    raise ValueError('Invalid desktop autosave acknowledgement')
                if inflight['epoch'] == self.epoch and inflight['path'] == self.path:
                    self.saved_hash, self.saved_revision = inflight['hash'], inflight['revision']
                    self.failures, self.error = 0, ''
                    self.next_due = now + self.interval
                    event = {'saved': True, 'revision': self.saved_revision}
            except (RuntimeError, OSError, ValueError) as exc:
                self.failures += 1
                self.error = str(exc)
                self.next_due = now + min(60.0, max(1.0, 2.0 ** min(self.failures, 5)))
                event = {'saved': False, 'error': self.error}
            finally:
                job.close()
        if not self.job and self.dirty and (force or now >= self.next_due):
            try:
                self.job = self.job_factory('board_save', self.path, deepcopy(self.pending))
                self.inflight = {'id': self.pending['id'], 'revision': self.pending['revision'],
                                 'hash': self.pending_hash, 'path': self.path, 'epoch': self.epoch}
            except (RuntimeError, OSError, ValueError) as exc:
                self.error = str(exc)
                self.failures += 1
                self.next_due = now + min(60.0, max(1.0, 2.0 ** min(self.failures, 5)))
                event = {'saved': False, 'error': self.error}
        return event
