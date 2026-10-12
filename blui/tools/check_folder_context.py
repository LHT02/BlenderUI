# SPDX-License-Identifier: GPL-2.0-or-later
"""Selected folders: real scoped menus arrive and refresh an already-open popup."""
import os
from pathlib import Path
import sys
import tempfile
import time
import bpy
from bl_ui import space_filebrowser_shell as shell_ui, space_filebrowser_explorer as menus

root = Path(tempfile.mkdtemp(prefix='blui_folder_context_'))
for name in ('one', 'two'):
    (root / name).mkdir()
state = {'step': 0, 'started': time.monotonic(), 'draws': []}
original_draw = menus.FILEBROWSER_MT_explorer_more.draw


def draw(self, context):
    original_draw(self, context)
    helper = state.get('helper')
    if helper:
        state['draws'].append(sum('root' in child.items for child in helper.helpers.values()))


menus.FILEBROWSER_MT_explorer_more.draw = draw


def override():
    return bpy.context.temp_override(window=state['window'], area=state['area'], region=state['region'])


def step():
    if time.monotonic() - state['started'] > 20:
        raise TimeoutError('Selected-folder popup did not finish')
    n = state['step']
    if n == 0:
        shell_ui.unregister()
        window = bpy.context.window_manager.windows[0]
        area = next(area for area in window.screen.areas if area.type == 'FILE_BROWSER')
        state.update(window=window, area=area, region=next(r for r in area.regions if r.type == 'WINDOW'))
        with override():
            bpy.ops.file.select_bookmark(dir=str(root))
        delay = .5
    elif n == 1:
        with override():
            bpy.ops.file.select_all(action='SELECT')
            entries = list(bpy.context.selected_files)
            assert len(entries) == 2 and all(entry.is_directory for entry in entries)
            helper = shell_ui.session(bpy.context)
            assert helper.kind == 'folder'
            state['helper'], state['load_started'] = helper, time.monotonic()
            bpy.ops.wm.call_menu(name='FILEBROWSER_MT_explorer_more')
        delay = .05
    elif n == 2:
        helper = state['helper']
        if helper.pending or 2 not in state['draws']:
            return .05
        assert all(not child.errors for child in helper.helpers.values()), {k: v.errors for k, v in helper.helpers.items()}
        assert state['draws'][0] == 0 and state['draws'][-1] == 2, state['draws']
        with override():
            assert shell_ui.session(bpy.context) is helper, 'Opening again did not reuse the cache'
            bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[3] / 'build/folder-context.png'))
        print('PASS Selected folders use two isolated scopes and update an open menu in %.3fs' %
              (time.monotonic() - state['load_started']), state['draws'], flush=True)
        for value in ('PRESS', 'RELEASE'):
            state['window'].event_simulate(type='ESC', value=value)
        delay = .1
    else:
        shell_ui.unregister()
        print('check_folder_context: PASS', flush=True)
        os._exit(0)
    state['step'] += 1
    return delay


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.5)
