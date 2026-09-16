# SPDX-License-Identifier: GPL-2.0-or-later
"""One filesystem task per subprocess; BLUI remains free to draw and navigate."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import file_tasks
from mailbox import publish, take

directory = sys.argv[1]
request = take(directory, 'task.json')
try:
    if request['function'] not in {'transfer', 'archive', 'extract_zip'}:
        raise ValueError('Unsupported file task')
    value = getattr(file_tasks, request['function'])(*request['args'])
    reply = {'ok': True, 'value': value}
except Exception as exc:
    reply = {'ok': False, 'error': str(exc)}
publish(directory, 'result.json', reply)
