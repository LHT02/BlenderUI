# SPDX-License-Identifier: GPL-2.0-or-later
"""Small future-like adapter polled by Blender's main-thread timer."""
import os
import shutil
import subprocess
import tempfile

from . import mailbox
from .shell_client import python_executable


class Job:
    def __init__(self, function, args):
        self.directory = tempfile.mkdtemp(prefix='blui_file_task_')
        self.process = None
        mailbox.publish(self.directory, 'task.json', {'function': function.__name__, 'args': args})

    def done(self):
        if self.process is None:
            self.process = subprocess.Popen(
                [python_executable(), '-I', '-u', os.path.join(os.path.dirname(__file__), 'task_worker.py'),
                 self.directory], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return self.process.poll() is not None

    def result(self):
        try:
            reply = mailbox.take(self.directory, 'result.json')
            if not reply:
                raise RuntimeError('File task exited unexpectedly; check the source and destination before retrying')
            if not reply['ok']:
                raise OSError(reply['error'])
            return reply['value']
        finally:
            shutil.rmtree(self.directory, ignore_errors=True)
