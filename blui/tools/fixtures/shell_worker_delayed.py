"""Deterministic delayed menu replies; never loads extensions or modifies files."""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/modules/blui_explorer'))
from mailbox import take, publish

directory = Path(sys.argv[1])
serial, generation = 1, 0
while directory.is_dir():
    request = take(directory, 'request-%d.json' % serial)
    if request is None:
        time.sleep(0.01)
        continue
    op = request['op']
    if op == 'list':
        generation += 1
        time.sleep(0.6)
        reply = {'ok': True, 'items': [
            {'label': 'Native extension command', 'enabled': True, 'separator': False, 'id': generation * 100 + 1},
            {'label': 'Delayed submenu', 'enabled': True, 'separator': False, 'id': 0, 'submenu': 'root/1'}]}
    elif op == 'expand':
        time.sleep(0.6)
        reply = {'ok': True, 'items': [
            {'label': 'Native child command', 'enabled': True, 'separator': False, 'id': generation * 100 + 2}]}
    elif op == 'status':
        reply = {'ok': True, 'has_dialogs': False}
    else:
        reply = {'ok': request.get('command') in {generation * 100 + 1, generation * 100 + 2},
                 'error': 'Command does not belong to this menu session'}
    publish(directory, 'reply-%d.json' % serial, reply)
    serial += 1
