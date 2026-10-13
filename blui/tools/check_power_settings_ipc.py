# SPDX-License-Identifier: GPL-2.0-or-later
"""Real helper admission for READONLY power and OWN temporary taskbar settings.

Uses bundled Python, not BLUI's GUI. Never invokes any power action, enables
hibernation, opens a program/location or touches user settings.
"""
from pathlib import Path
import os
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
from blui_desktop import client, system_power, taskbar_settings


def result(action, *args):
    job = client.Job(action, *args, timeout=8)
    try:
        deadline = time.monotonic() + 10
        while not job.done() and time.monotonic() < deadline:
            time.sleep(.02)
        assert job.done(), (action, 'isolated helper did not finish')
        return job.result()
    finally:
        job.close()


def main():
    assert os.name == 'nt', 'Real power capability QA requires Windows'
    detected = system_power.validate(result('start_capabilities'))
    assert detected == system_power.capabilities(), 'Helper capability changed or IPC was invalid'
    with tempfile.TemporaryDirectory(prefix='blui_power_settings_ipc_') as directory:
        assert result('taskbar_settings_load', directory) == taskbar_settings.defaults()
        changed = taskbar_settings.changed(taskbar_settings.defaults(), height=96, icon_size=48)
        assert result('taskbar_settings_save', directory, changed) is True
        assert result('taskbar_settings_load', directory) == changed
        raw = (Path(directory) / 'taskbar-settings.json').read_bytes()
        assert not raw.startswith(b'\xef\xbb\xbf')
    print('PASS real isolated power READONLY detection', detected,
          '+ taskbar settings load/save/readback in OWN temporary folder; ZERO suspend/shutdown/configuration changes')


if __name__ == '__main__':
    main()
