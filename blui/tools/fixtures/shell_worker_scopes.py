# SPDX-License-Identifier: GPL-2.0-or-later
"""Two hosts deliberately share native IDs; client routing must keep them separate."""
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/modules/blui_explorer'))
from mailbox import publish, take

directory = Path(sys.argv[1])
serial = 1
scope = None
while directory.is_dir():
    request = take(directory, 'request-%d.json' % serial)
    if request is None:
        time.sleep(.01)
        continue
    reply = {'ok': True}
    if request['op'] == 'list':
        scope = request.get('scope')
        time.sleep(.05 if scope == 'folder' else .25)
        reply['items'] = [dict(label=scope, enabled=True, separator=False, id=1),
                          dict(label=scope + '-child', enabled=True, separator=False, id=2, submenu='root/1')]
    elif request['op'] == 'expand':
        reply['items'] = [dict(label=scope + '-child-command', enabled=True, separator=False, id=3)]
    elif request['op'] == 'invoke':
        # This response proves the client dispatched the right host and native ID.
        reply = {'ok': False, 'error': '%s:%d' % (scope, request['command'])}
    elif request['op'] == 'status':
        reply['has_dialogs'] = False
    publish(directory, 'reply-%d.json' % serial, reply)
    serial += 1
