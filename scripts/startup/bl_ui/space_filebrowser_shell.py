# SPDX-License-Identifier: GPL-2.0-or-later
"""Selection preloading and live popup updates; Shell DLLs stay in the helper."""
import itertools
import os
import sys
import time

import bpy
from bpy.types import Menu
from bl_operators.blui_file import directory, selected_paths
from blui_explorer import shell_client
from blui_explorer.localization import iface, message

bindings = {}
_dynamic = []
_menu_ids = itertools.count()
_observed = {}


def popup_key(session, node):
    return session.token + ':' + node


def _draw_submenu(self, context):
    from bl_ui.space_filebrowser_explorer import _native_items
    _native_items(self.layout, context, shell_client.sessions.get(self.session_token), self.node_key)


def tick():
    for token, session in list(shell_client.sessions.items()):
        if session.poll():
            for items in session.items.values():
                if not isinstance(items, list):
                    continue
                for item in items:
                    child = item.get('submenu')
                    if child and (token, child) not in bindings:
                        name = 'FILEBROWSER_MT_shell_' + str(next(_menu_ids))
                        cls = type(name, (Menu,), {
                            'bl_label': item['label'] or 'Windows',
                            'draw': _draw_submenu,
                            'session_token': token, 'node_key': child,
                        })
                        bpy.utils.register_class(cls)
                        _dynamic.append(cls)
                        bindings[token, child] = name
            for node in session.updated_nodes:
                bpy.context.window_manager.tag_menu_refresh(popup_key(session, node))
            if session.items.pop('invoke', False):
                from bl_operators.blui_file import refresh_all
                refresh_all()
            if 'invoke' in session.errors and not getattr(session, 'error_shown', False):
                session.error_shown = True
                text = message(session.errors['invoke'])
                def draw_error(self, _context, text=text):
                    for start in range(0, len(text), 75):
                        self.layout.label(text=text[start:start + 75], translate=False)
                bpy.context.window_manager.popup_menu(draw_error, title=iface('Windows Command'), icon='ERROR')
        if time.monotonic() - session.last_used > 120 and not session.pending and not session.invoked:
            session.close()
            del shell_client.sessions[token]
        elif not session.is_alive() and not session.pending:
            session.close()
            del shell_client.sessions[token]
        elif session.invoked and not session.pending and time.monotonic() - max(session.last_used, session.last_status) > 3:
            session.request('status')
    for cls in list(_dynamic):
        if cls.session_token not in shell_client.sessions:
            # An old popup may still reference this class until the user moves away.
            # Keep its draw callback valid; its missing session shows a clear message.
            if not bpy.context.window_manager.tag_menu_refresh(cls.session_token + ':' + cls.node_key):
                bindings.pop((cls.session_token, cls.node_key), None)
                bpy.utils.unregister_class(cls)
                _dynamic.remove(cls)
    return 0.05 if shell_client.sessions else None


def ensure_tick():
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=0.025)


def session(context, retry=False):
    entries = [entry for entry in (getattr(context, 'selected_files', None) or ())
               if entry.relative_path not in {'', '.', '..'}]
    paths = selected_paths(context) or [os.path.normpath(directory(context))]
    folders = not entries or all(entry.is_directory for entry in entries)
    try:
        result = shell_client.get_session(paths, retry=retry, folders=folders)
        ensure_tick()
        return result
    except (OSError, RuntimeError) as exc:
        print('BLUI Shell:', exc)
        return None


def _preload_selection():
    now = time.monotonic()
    active = set()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            space = area.spaces.active
            if area.type != 'FILE_BROWSER' or space.active_operator or space.browse_mode != 'FILES' or not space.params:
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if not region:
                continue
            area_key = area.as_pointer()
            active.add(area_key)
            with bpy.context.temp_override(window=window, area=area, region=region):
                root = directory(bpy.context)
                if not root:
                    continue
                paths = tuple(selected_paths(bpy.context) or [os.path.normpath(root)])
                previous = _observed.get(area_key)
                if not previous or previous[0] != paths:
                    _observed[area_key] = (paths, now)
                elif now - previous[1] >= 0.2:
                    # Start once after the selection settles, before right-click.
                    if previous[1] != float('inf'):
                        session(bpy.context)
                        _observed[area_key] = (paths, float('inf'))
    for key in set(_observed) - active:
        del _observed[key]
    return 0.12


def register():
    if sys.platform == 'win32' and not bpy.app.background and not bpy.app.timers.is_registered(_preload_selection):
        bpy.app.timers.register(_preload_selection, first_interval=0.5, persistent=True)


def unregister():
    for callback in (_preload_selection, tick):
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
    shell_client.close_all()
    for cls in reversed(_dynamic):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    _dynamic.clear()
    bindings.clear()
    _observed.clear()
