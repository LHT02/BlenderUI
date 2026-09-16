# SPDX-License-Identifier: GPL-2.0-or-later
"""Native event-loop regression on a check_explorer.py disposable fixture."""
import os
from pathlib import Path
import sys
import time
import bpy
from bl_operators import blui_file
from bl_ui import space_filebrowser_explorer as menus
from blui_explorer import shell_client

root = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
assert root.name.startswith('blui_explorer_qa_') and (root / 'Folder/inside.txt').is_file()
if not (root / 'new.txt').exists() and (root / 'Folder/new.txt').is_file():
    (root / 'Folder/new.txt').rename(root / 'new.txt')
output = Path(__file__).resolve().parents[3] / 'build'
state = {'step': 0, 'started': time.monotonic(), 'failures': []}


def report(ok, text):
    print(('PASS ' if ok else 'FAIL ') + text, flush=True)
    if not ok:
        state['failures'].append(text)


def context():
    return bpy.context.temp_override(window=state['window'], area=state['area'], region=state['region'])


def event(kind, value, x=930, top=140):
    win = state['window']
    win.event_simulate(type=kind, value=value, x=round(x * win.width / 2560),
                       y=win.height - round(top * win.width / 2560))


def capture(name):
    with context():
        bpy.ops.screen.screenshot(filepath=str(output / (name + '.png')))


def step():
    n = state['step']
    if time.monotonic() - state['started'] > 45:
        raise TimeoutError('Input regression timed out')
    if n == 0:
        win = bpy.context.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == 'FILE_BROWSER')
        state.update(window=win, area=area, region=next(r for r in area.regions if r.type == 'WINDOW'))
        with context():
            bpy.ops.file.select_bookmark(dir=str(root))
            area.spaces.active.params.display_type = 'THUMBNAIL'
        delay = 1.2
    elif n == 1:
        with context():
            bpy.ops.file.select_all(action='DESELECT')
        event('MOUSEMOVE', 'NOTHING')
        event('LEFTMOUSE', 'PRESS')
        delay = 0.2
    elif n == 2:
        event('MOUSEMOVE', 'NOTHING', x=950)
        delay = 0.2
    elif n == 3:
        event('MOUSEMOVE', 'NOTHING', x=475)
        delay = 0.8
    elif n == 4:
        capture('explorer-drag')
        event('LEFTMOUSE', 'RELEASE', x=475)
        delay = 0.8
    elif n == 5:
        if blui_file._jobs:
            return 0.2
        if not state.get('after_drop_refresh'):
            state['after_drop_refresh'] = True
            return 0.8
        report((root / 'Folder/new.txt').is_file() and not (root / 'new.txt').exists(),
               'Native mouse drag moves a file into the hovered folder')
        event('MOUSEMOVE', 'NOTHING', x=625)
        event('LEFTMOUSE', 'PRESS', x=625)
        event('LEFTMOUSE', 'RELEASE', x=625)
        delay = 0.8
    elif n == 6:
        if not state.get('opened_shortcut'):
            with context():
                print('SHORTCUT BEFORE', blui_file.directory(bpy.context),
                      [f.relative_path for f in bpy.context.selected_files],
                      getattr(bpy.context.active_file, 'relative_path', None), flush=True)
                bpy.ops.file.execute()
            state['opened_shortcut'] = True
            return 0.8
        with context():
            print('SHORTCUT AFTER', blui_file.directory(bpy.context), flush=True)
            report(Path(blui_file.directory(bpy.context)).resolve() == root / 'Folder',
                   'Opening a folder shortcut navigates to its target')
            bpy.ops.file.select_bookmark(dir=str(root))
        delay = 0.8
    elif n == 7:
        if not state.get('clicked_file'):
            event('MOUSEMOVE', 'NOTHING', x=1075)
            event('LEFTMOUSE', 'PRESS', x=1075)
            event('LEFTMOUSE', 'RELEASE', x=1075)
            state['clicked_file'] = True
            return 0.3
        with context():
            bpy.ops.wm.call_menu(name='FILEBROWSER_MT_context_menu')
            state['session'] = menus._session(bpy.context)
        delay = 1.2
    elif n == 8:
        capture('explorer-context')
        event('ESC', 'PRESS')
        event('ESC', 'RELEASE')
        delay = 0.3
    elif n == 9:
        if state['session'].pending:
            return 0.2
        print('UI SHELL', state['session'].paths, state['session'].errors, flush=True)
        with context():
            bpy.ops.wm.call_menu(name='FILEBROWSER_MT_explorer_more')
        delay = 1.0
    elif n == 10:
        capture('explorer-more')
        event('ESC', 'PRESS')
        event('ESC', 'RELEASE')
        delay = 0.3
    elif n == 11:
        session = state['session']
        item = next((i for i in session.items.get('root', []) if i['label'] == '7-Zip'), None)
        report(bool(item and session.items.get(item['submenu'])), 'Real 7-Zip submenu loaded in UI session')
        if item:
            with context():
                bpy.ops.wm.call_menu(name=menus._bindings[session.token, item['submenu']])
        delay = 0.5
    elif n == 12:
        capture('explorer-7zip')
        event('ESC', 'PRESS')
        event('ESC', 'RELEASE')
        delay = 0.2
    else:
        shell_client.close_all()
        print('check_explorer_interaction:', 'FAIL' if state['failures'] else 'PASS', flush=True)
        os._exit(bool(state['failures']))
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


bpy.app.timers.register(guarded, first_interval=1.0)
