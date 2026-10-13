# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded async power capability cache; Start menu draw reads RAM only."""
import time
from . import client, system_power

_job = None
_value = {'hibernate': False}
_due = 0.0


def snapshot():
    return dict(_value)


def tick(active=False):
    global _job, _value, _due
    changed = False
    if _job is not None and _job.done():
        job, _job = _job, None
        try:
            value = system_power.validate(job.result())
        except (RuntimeError, OSError, ValueError):
            value = {'hibernate': False}
        finally:
            job.close()
        changed, _value = value != _value, value
    if active and _job is None and time.monotonic() >= _due:
        try:
            _job = client.Job('start_capabilities', timeout=4)
            _due = time.monotonic() + 30
        except (RuntimeError, ValueError):
            _due = time.monotonic() + .5
    return changed


def close():
    global _job, _value, _due
    if _job is not None:
        _job.close()
    _job, _value, _due = None, {'hibernate': False}, 0.0
