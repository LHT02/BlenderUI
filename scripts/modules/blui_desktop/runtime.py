# SPDX-License-Identifier: GPL-2.0-or-later
"""Main-thread RNA updates. No retained area/region pointers across asynchronous work."""
import os
import hashlib
import json
import time
import uuid
import bpy
from bpy.app.handlers import persistent
from . import background, client, model, serialization, icon_cache, thumbnail_cache, session, weather_runtime
from blui_explorer.localization import iface

_jobs = []
_tasks = []
_task_error = ''
_last_tasks = 0.0
_keymaps = []
_origins = {}
_expected = {}
_ready = []
_epoch = 0
_monitors = {'coordinate_space': 'physical', 'monitors': []}
_last_monitors = 0.0
_background_due = {}
_preview_paths = {}
_shell_retry_due = 0.0
_reservation_state = None


def identity(tree):
    if not tree.service_identity:
        tree.service_identity = uuid.uuid4().hex
    return (tree.as_pointer(), tree.service_identity, _epoch)


def resolve_tree(token):
    if not token or token[2] != _epoch:
        return None
    return next((tree for tree in bpy.data.node_groups if tree.bl_idname == model.TREE and
                 tree.as_pointer() == token[0] and tree.service_identity == token[1]), None)


def layout_path(tree):
    if not tree.layout_key:
        tree.layout_key = uuid.uuid4().hex
    if len(tree.layout_key) != 32 or any(char not in '0123456789abcdef' for char in tree.layout_key):
        raise ValueError('Invalid canvas identity')
    folder = bpy.utils.user_resource('CONFIG', path='blui_desktop')
    return os.path.join(folder, tree.layout_key + '.json')


def snapshot(tree):
    return serialization.snapshot(tree)


def apply_layout(tree, payload):
    serialization.apply(tree, payload)


def add_files(tree, rows, origin=(0, 0), *, selected=True):
    existing = {os.path.normcase(node.filepath): node for node in tree.nodes if node.bl_idname == model.FILE}
    count = 0
    for row in rows:
        key = os.path.normcase(row['path'])
        if key in existing:
            existing[key].label, existing[key].folder = row['name'], row['folder']
            continue
        if len(tree.nodes) >= model.LIMIT:
            break
        node = tree.nodes.new(model.FILE)
        node.filepath, node.label, node.folder = row['path'], row['name'], row['folder']
        node.select = selected
        node.location = (origin[0] + (count % 8) * 150, origin[1] - (count // 8) * 140)
        existing[key] = node
        count += 1
    return count


def submit(action, tree=None, *args):
    if len(_jobs) + len(_ready) >= 8:
        raise RuntimeError('Desktop service is busy; try again shortly')
    token = identity(tree) if tree else None
    generation = tree.scan_generation if tree else 0
    if action == 'scan':
        tree.scan_generation += 1
        generation = tree.scan_generation
    elif action == 'background':
        tree.background_generation += 1
        generation = tree.background_generation
    job = client.Job(action, *args)
    _jobs.append((job, action, token, generation))
    if action == 'previews':
        _preview_paths[id(job)] = list(args[0])
    if action == 'paths' and tree:
        space = bpy.context.space_data
        _origins[id(job)] = tuple(space.cursor_location) if space and space.type == 'NODE_EDITOR' else (0, 0)
    if action == 'load' and tree:
        _expected[id(job)] = fingerprint(tree)
    if tree:
        tree.service_status = iface('Loading...')
    return job


def tasks():
    return _tasks


def monitor_snapshot():
    return _monitors


def queue_weather(tree, node, force=True):
    weather_runtime.queue(__import__(__name__, fromlist=['']), tree, node, force)


def task_error():
    return _task_error


def fingerprint(tree):
    return hashlib.sha256(json.dumps(snapshot(tree), ensure_ascii=True).encode('utf-8')).hexdigest()


def interaction_busy(tree):
    # A transform may still own nodes after a workspace/editor switch. Conservatively gate all windows.
    return any(window.blui_has_modal_interaction for window in bpy.context.window_manager.windows)


def shell_interaction_busy():
    # Private INFO/WM shell lists never mutate document/node RNA. An ordinary
    # hover in a NORMAL editor must not starve their async updates. Native shell
    # classification still protects editing, popups, dragging and held buttons.
    return any(window.blui_shell_role not in {'NORMAL', 'DESKTOP'} and window.blui_has_modal_interaction
               for window in bpy.context.window_manager.windows)


@persistent
def cancel_pending(_dummy=None):
    # Undo/file loading replaces Main/RNA identities. Never apply old results to a new Main.
    client.close_all()
    global _epoch
    _epoch += 1
    from . import desktop_service
    desktop_service.cancel_pending()  # Undo detaches safely without closing canvas RNA.
    _jobs.clear()
    _ready.clear()
    _origins.clear()
    _expected.clear()
    session.reset(_epoch)
    weather_runtime.reset()
    _background_due.clear()
    background.clear()
    thumbnail_cache.cancel_pending()
    _preview_paths.clear()
    from . import start_menu
    start_menu.close()
    from . import power_state
    power_state.close()
    from . import folder_panels
    folder_panels.close()
    from . import shell_hover, taskbar_previews, taskbar_appbar, taskbar_settings, notification_client
    shell_hover.close()
    from . import notification_hover
    notification_hover.close()
    taskbar_previews.close_all()
    taskbar_appbar.close_all()
    taskbar_settings.shutdown()
    notification_client.close()
    from .file_actions import clear_drag
    clear_drag()


def tick():
    global _tasks, _task_error, _last_tasks, _monitors, _last_monitors, _shell_retry_due, _reservation_state
    live = [(window, area) for window in bpy.context.window_manager.windows for area in window.screen.areas
            if area.type == 'NODE_EDITOR']
    shell = [(window, area) for window in bpy.context.window_manager.windows for area in window.screen.areas
             if getattr(window, 'blui_shell_role', 'NORMAL') not in {'NORMAL', 'DESKTOP'}]
    from . import taskbar_windows
    from . import desktop_service
    service_live = live or shell or taskbar_windows.needs_service() or desktop_service.needs_service()
    from . import folder_panels
    folder_panels.tick(__import__(__name__, fromlist=['']), live)
    from . import start_menu
    start_menu.tick()
    from . import power_state
    power_state.tick(any(window.blui_shell_role == 'STARTMENU' for window in bpy.context.window_manager.windows))
    from . import taskbar_settings, taskbar_options_ui, notification_client, session
    if service_live:
        taskbar_settings.service_tick(session.storage_directory())
        taskbar_options_ui.sync()
    if taskbar_windows.role_windows('TASKBAR') and not session.disable_for_tests:
        notification_client.start()
    elif not taskbar_windows.role_windows('TASKBAR'):
        notification_client.close()
    notification_client.poll()
    from . import taskbar
    reservation = taskbar.snapshot()
    reservation_key = (reservation.get('reservation_reclaimed'), reservation.get('reservation_pending'))
    if reservation_key != _reservation_state:
        _reservation_state, _last_monitors = reservation_key, 0.0
        taskbar_windows._appbar.invalidate()
    if not bpy.context.window_manager.blui_has_path_drag:
        from .file_actions import clear_drag
        clear_drag()
    for job, action, token, generation in list(_jobs):
        if not job.done():
            continue
        _jobs.remove((job, action, token, generation))
        tree = resolve_tree(token)
        try:
            value = job.result()
            if action == 'tasks':
                _tasks, _task_error = value, ''
            elif action == 'task_launch':
                _task_error, _last_tasks = '', 0.0
            elif action == 'monitors':
                _monitors = value
            elif action == 'board_load':
                session.receive(value)
            elif action == 'icons':
                icon_cache.apply(value)
            elif action == 'previews':
                thumbnail_cache.apply(value)
            elif action == 'background' and tree:
                if tree.background_generation == generation:
                    _ready.append((action, token, generation, value, (0, 0), ''))
            elif action == 'weather':
                weather_runtime.receive(__import__(__name__, fromlist=['']), job, value)
            elif tree and tree.scan_generation == generation:
                if action in {'scan', 'paths', 'load'}:
                    _ready.append((action, token, generation, value, _origins.get(id(job), (0, 0)), _expected.get(id(job), '')))
                else:
                    tree.service_status = iface('Canvas layout saved')
        except (RuntimeError, OSError, ValueError) as exc:
            if action in {'tasks', 'task_launch'}:
                _task_error = str(exc)
            elif action == 'board_load':
                session.missing()
                for root in session.roots():
                    if not root.nodes:
                        try:
                            submit('scan', root, root.directory)
                        except RuntimeError:
                            pass
            elif action == 'weather':
                weather_runtime.failed(__import__(__name__, fromlist=['']), job, str(exc))
            elif action == 'previews':
                thumbnail_cache.fail(_preview_paths.get(id(job), ()))
            elif tree:
                tree.service_status = str(exc)
        finally:
            _origins.pop(id(job), None)
            _expected.pop(id(job), None)
            _preview_paths.pop(id(job), None)
    for item in list(_ready):
        action, token, generation, value, origin, expected = item
        tree = resolve_tree(token)
        if not tree or (tree.background_generation if action == 'background' else tree.scan_generation) != generation:
            _ready.remove(item)
            continue
        if interaction_busy(tree):
            continue
        owner = next(((window, area) for window, area in live if
                      (area.spaces.active.node_tree if action == 'background' else
                       area.spaces.active.edit_tree or area.spaces.active.node_tree) == tree), None)
        if not owner:
            continue
        _ready.remove(item)
        try:
            if action == 'background':
                background.apply(tree, value)
                tree.service_status = iface('Background loaded')
                continue
            if expected and fingerprint(tree) != expected:
                tree.service_status = iface('Canvas changed; request restoration again')
                continue
            window, area = owner
            region = next((region for region in area.regions if region.type == 'WINDOW'), None)
            with bpy.context.temp_override(window=window, area=area, region=region):
                result = bpy.ops.wm.blui_canvas_apply('EXEC_DEFAULT', True, action=action, payload=json.dumps(value), origin=origin)
            if result != {'FINISHED'}:
                tree.service_status = iface('Canvas update cancelled')
        except (RuntimeError, ReferenceError, ValueError, TypeError) as exc:
            current = resolve_tree(token)
            if current:
                current.service_status = str(exc)
    if service_live and os.name == 'nt' and time.monotonic() - _last_tasks > 3 and not any(action == 'tasks' for _job, action, _id, _generation in _jobs):
        try:
            submit('tasks')
        except (RuntimeError, OSError) as exc:
            _task_error = str(exc)
        _last_tasks = time.monotonic()
    if service_live:
        module = __import__(__name__, fromlist=[''])
        if session.roots():
            try:
                session.begin(module)
            except RuntimeError:
                pass
        session.tick(module)
        weather_runtime.tick(module)
        from . import displays, taskbar, taskbar_windows
        displays.topology_changed(_monitors)
        if time.monotonic() >= _shell_retry_due:
            try:
                taskbar_windows.tick(_monitors)
                _shell_retry_due = 0.0
            except (RuntimeError, OSError, ValueError, ReferenceError) as exc:
                _task_error = str(exc)
                _shell_retry_due = time.monotonic() + 3.0
        state = taskbar.tick()
        from . import shell_hover
        try:
            shell_hover.tick()
        except (RuntimeError, OSError, ValueError, ReferenceError) as exc:
            _task_error = str(exc)
            shell_hover.close()
        if state.get('tasks_revision', 0) != globals().get('_task_revision', 0):
            globals()['_task_revision'] = state['tasks_revision']
            _last_tasks = 0
        if time.monotonic() - _last_monitors > 3 and not any(action == 'monitors' for _job, action, _id, _gen in _jobs):
            try:
                submit('monitors')
                _last_monitors = time.monotonic()
            except RuntimeError:
                pass
        # Icon admission only consumes RAM and starts an isolated job; it never
        # changes Node/Area RNA. A lingering NORMAL hover must not starve shell
        # application/Start icons. Node and thumbnail guards stay conservative.
        icons_allowed = not interaction_busy(None) or (shell and not shell_interaction_busy())
        if icons_allowed and not any(action == 'icons' for _job, action, _id, _gen in _jobs):
            paths = icon_cache.pending()
            if paths:
                try:
                    submit('icons', None, paths)
                except RuntimeError:
                    icon_cache.retry(paths)
        if not interaction_busy(None) and not any(action == 'previews' for _job, action, _id, _gen in _jobs):
            paths = thumbnail_cache.pending()
            if paths:
                try:
                    submit('previews', None, paths)
                except RuntimeError:
                    thumbnail_cache.retry(paths)
        if not interaction_busy(None):
            for root in session.roots():
                key = (identity(root), root.background_path)
                if root.background_enabled and root.background_path and not background.has_image(root) and time.monotonic() >= _background_due.get(key, 0):
                    try:
                        submit('background', root, root.background_path)
                        _background_due[key] = time.monotonic() + 30
                    except RuntimeError:
                        break
    desktop_service.tick(_monitors)  # May close only its OWN DESKTOP, after all old live-area consumers.
    # Shell services may close a popup during this tick. Never dereference
    # areas captured before those closures (RNA Window/Screen may already be freed).
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'NODE_EDITOR' or window.blui_shell_role != 'NORMAL':
                area.tag_redraw()
    return .1 if shell or _jobs or _ready or start_menu.busy() or desktop_service.needs_service() else 1.0


def register():
    from . import start_menu_ui, taskbar_windows, taskbar_options_ui, notification_ui
    start_menu_ui.register_props()
    taskbar_options_ui.register_props()
    notification_ui.register_props()
    taskbar_windows.register()
    background.register(monitor_snapshot)
    from . import desktop_service
    if desktop_service.load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(desktop_service.load_pre)
    for handlers in (bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre, bpy.app.handlers.load_pre):
        if cancel_pending not in handlers:
            handlers.append(cancel_pending)
    if not bpy.app.background and not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=1.0, persistent=True)
    kc = bpy.context.window_manager.keyconfigs.addon
    if not kc:
        return
    tool = kc.keymaps.new(name='Node Tool: All, Select Box', space_type='NODE_EDITOR', region_type='WINDOW', tool=True)
    item = tool.keymap_items.new('node.select_box', 'LEFTMOUSE', 'CLICK_DRAG')
    item.properties.wait_for_input, item.properties.tweak, item.properties.mode = False, True, 'SET'
    _keymaps.append((tool, item))
    generic = kc.keymaps.new(name='Node Generic', space_type='NODE_EDITOR')
    item = generic.keymap_items.new('wm.context_toggle', 'N', 'PRESS')
    item.properties.data_path = 'space_data.show_region_ui'
    _keymaps.append((generic, item))
    km = kc.keymaps.new(name='Node Editor', space_type='NODE_EDITOR')
    for operator, key, value, modifiers, properties in (
        ('node.group_make', 'G', 'PRESS', {'ctrl': True}, {}),
        ('node.group_ungroup', 'G', 'PRESS', {'alt': True}, {}),
        ('wm.blui_canvas_frame_selected', 'P', 'PRESS', {'shift': True}, {}),
        ('node.group_edit', 'TAB', 'PRESS', {}, {}),
        ('node.group_edit', 'TAB', 'PRESS', {'ctrl': True}, {'exit': True}),
        ('wm.blui_canvas_open_active', 'LEFTMOUSE', 'DOUBLE_CLICK', {}, {}),
        ('wm.blui_canvas_files', 'C', 'PRESS', {'ctrl': True}, {'action': 'COPY'}),
        ('wm.blui_canvas_files', 'X', 'PRESS', {'ctrl': True}, {'action': 'CUT'}),
        ('wm.blui_canvas_files', 'V', 'PRESS', {'ctrl': True}, {'action': 'PASTE'}),
        ('wm.blui_canvas_files', 'F2', 'PRESS', {}, {'action': 'RENAME'}),
        ('node.select', 'LEFTMOUSE', 'PRESS', {}, {'deselect_all': True, 'select_passthrough': True}),
        ('node.select', 'LEFTMOUSE', 'CLICK', {}, {'deselect_all': True}),
        ('node.select', 'LEFTMOUSE', 'PRESS', {'shift': True}, {'extend': True}),
        ('node.translate_attach', 'LEFTMOUSE', 'CLICK_DRAG', {}, {}),
        ('node.translate_attach', 'G', 'PRESS', {}, {}),
        ('node.select_all', 'A', 'PRESS', {}, {'action': 'SELECT'}),
        ('node.select_all', 'A', 'PRESS', {'alt': True}, {'action': 'DESELECT'}),
        ('node.select_box', 'B', 'PRESS', {}, {}),
        ('node.view_all', 'HOME', 'PRESS', {}, {}),
        ('node.view_selected', 'NUMPAD_PERIOD', 'PRESS', {}, {}),
        ('node.delete', 'X', 'PRESS', {}, {}),
        ('node.delete', 'DEL', 'PRESS', {}, {}),
        ('wm.call_menu', 'RIGHTMOUSE', 'PRESS', {}, {'name': 'BLUI_MT_canvas_context'}),
    ):
        item = km.keymap_items.new(operator, key, value, **modifiers)
        for name, value in properties.items():
            setattr(item.properties, name, value)
        _keymaps.append((km, item))


def unregister():
    from . import desktop_service
    desktop_service.shutdown()
    if desktop_service.load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(desktop_service.load_pre)
    from . import start_menu_ui, taskbar, taskbar_windows, taskbar_options_ui, notification_ui
    taskbar_windows.close()
    taskbar_windows.unregister()
    start_menu_ui.unregister_props()
    taskbar_options_ui.unregister_props()
    notification_ui.unregister_props()
    taskbar.close()
    background.unregister()
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    for km, item in _keymaps:
        km.keymap_items.remove(item)
    _keymaps.clear()
    for handlers in (bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre, bpy.app.handlers.load_pre):
        if cancel_pending in handlers:
            handlers.remove(cancel_pending)
    cancel_pending()
    icon_cache.close()
    thumbnail_cache.close()
