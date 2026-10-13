# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only real Windows Programs and isolated IPC acceptance; no application launch."""
import os
from pathlib import Path
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
from blui_desktop import client, start_menu_backend as backend, start_menu_model as schema


def main():
    if os.name != 'nt':
        print('SKIP: real Windows Start menu check requires Windows')
        return
    with tempfile.TemporaryDirectory(prefix='blui_start_index_qa_') as directory:
        begin = time.perf_counter()
        job = client.Job('start_index', directory, timeout=12)
        deadline = time.monotonic() + 15
        while not job.done() and time.monotonic() < deadline:
            time.sleep(.02)
        if not job.done():
            job.close()
            raise AssertionError('The Start menu index did not finish in its bounded worker')
        result = schema.validate_index(job.result())
        if result['errors']:
            raise AssertionError('Programs KnownFolder scan failed: ' + result['errors'][0])
        checked = 0
        roots = backend._program_roots()
        for row in result['rows']:
            # Filesystem identity checks ONLY; no ShellExecute, shortcuts resolved or apps opened.
            assert backend.validated_target(row, roots) == row['path']
            checked += 1
        assert not (Path(directory) / 'start-menu.json').exists(), 'Reading the index must not create preferences'
        print(f'PASS: isolated Start menu index {len(result["rows"])} apps, '
              f'{checked} validated targets, truncated={result["truncated"]}, '
              f'{time.perf_counter() - begin:.3f}s; zero launches/power changes')


if __name__ == '__main__':
    main()
