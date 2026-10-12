# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify a popup updates from delayed IPC without a second call_menu/right-click."""
import os
from pathlib import Path
import sys
import tempfile
import time
import bpy
from bl_operators.blui_file import selected_paths
from bl_ui import space_filebrowser_explorer as menus, space_filebrowser_shell as shell_ui
from blui_explorer import shell_client, localization

root = Path(tempfile.mkdtemp(prefix='blui_live_menu_'))
(root / 'fixture.txt').write_text('fixture', encoding='utf-8')
state = {'step': 0, 'started': time.monotonic(), 'more_draws': [], 'child_draws': []}
original_draw = menus.FILEBROWSER_MT_explorer_more.draw


def more_draw(self, context):
    original_draw(self, context)
    session = state.get('session')
    state['more_draws'].append(bool(session and 'root' in session.items))


menus.FILEBROWSER_MT_explorer_more.draw = more_draw


def override():
    return bpy.context.temp_override(window=state['window'], area=state['area'], region=state['region'])


def escape():
    for value in ('PRESS', 'RELEASE'):
        state['window'].event_simulate(type='ESC', value=value)


def step():
    if time.monotonic() - state['started'] > 20:
        raise TimeoutError('Live menu did not update')
    n = state['step']
    if n == 0:
        shell_ui.unregister()
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == 'FILE_BROWSER')
        state.update(window=window, area=area, region=next(r for r in area.regions if r.type == 'WINDOW'))
        prefs = bpy.context.preferences.view
        prefs.language = 'zh_CN'
        prefs.use_translate_interface = True
        prefs.use_translate_tooltips = True
        assert localization.iface('Copy To...') == '复制到...'
        assert localization.message('Already exists (nothing overwritten): X') == '已有同名项目（未覆盖）：X'
        assert bpy.app.translations.pgettext_tip('Rename this item without overwriting another file', 'Operator') != 'Rename this item without overwriting another file'
        prefs.use_translate_interface = False
        assert localization.iface('Copy To...') == 'Copy To...'
        prefs.use_translate_interface = True
        prefs.language = 'zh_TW'
        assert localization.iface('Copy To...') == '複製到...'
        prefs.language = 'zh_CN'
        with override():
            bpy.ops.file.select_bookmark(dir=str(root))
        print('PASS Simplified/Traditional/disabled translation settings', flush=True)
        delay = 0.8
    elif n == 1:
        with override():
            bpy.ops.file.select_all(action='SELECT')
            paths = selected_paths(bpy.context)
            helper = shell_client.Session(paths, worker=str(Path(__file__).parent / 'fixtures/shell_worker_delayed.py'))
            shell_client.sessions[helper.token] = helper
            state['session'] = helper
            shell_ui.ensure_tick()
            bpy.ops.wm.call_menu(name='FILEBROWSER_MT_explorer_more')
        delay = 0.1
    elif n == 2:
        if not any(state['more_draws']):
            return 0.1
        assert state['more_draws'][0] is False and state['more_draws'][-1] is True, state['more_draws']
        assert 'root/1' not in state['session'].items, 'Submenu was loaded eagerly'
        print('PASS Open More menu updated in place after delayed result', state['more_draws'], flush=True)
        escape()
        delay = 0.2
    elif n == 3:
        helper = state['session']
        cls = getattr(bpy.types, shell_ui.bindings[helper.token, 'root/1'])
        original = cls.draw
        def child_draw(self, context):
            original(self, context)
            state['child_draws'].append('root/1' in helper.items)
        cls.draw = child_draw
        with override():
            bpy.ops.wm.call_menu(name=cls.__name__)
        delay = 0.1
    elif n == 4:
        if not any(state['child_draws']):
            return 0.1
        assert state['child_draws'][0] is False and state['child_draws'][-1] is True, state['child_draws']
        print('PASS Open delayed child menu updated in place', state['child_draws'], flush=True)
        escape()
        delay = 0.2
    else:
        shell_ui.unregister()
        print('check_explorer_live_menu: PASS', flush=True)
        os._exit(0)
    state['step'] += 1
    return delay


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        shell_client.close_all()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=0.5)
