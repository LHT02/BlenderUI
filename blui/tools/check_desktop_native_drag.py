# SPDX-License-Identifier: GPL-2.0-or-later
"""Real mouse events exercise native desktop icon/path drag and drop.

Run sequentially, after building, in a dedicated QA process:
  BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python <script>

Only this process's two newly created HWNDs and temporary files are touched. No user CONFIG,
clipboard, network, system taskbar, display settings or foreign window writes.
Two windows on one physical display deliberately exercise the cross-window
path. This does not claim to simulate unplugging a monitor or mixed-DPI hardware.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import sys
import tempfile
import time

import bpy
from bl_operators import blui_desktop, blui_file
from bl_ui import space_filebrowser_shell
from blui_desktop import file_actions, icon_cache, model, runtime, session, window_placement


fixture = tempfile.TemporaryDirectory(prefix='blui_native_icon_drag_')
folder = Path(fixture.name)
os.environ['BLUI_DESKTOP_CONFIG'] = str(folder / 'config')
session.disable_for_tests = True
source_files = [folder / 'native-a.txt', folder / 'native-b.txt']
for index, path in enumerate(source_files):
    path.write_text('owned native drag fixture ' + str(index), encoding='utf-8')
destination = folder / 'TargetFolder'
destination.mkdir()
state = {'phase': 0, 'started': time.monotonic(), 'drops': [], 'transfers': [], 'bridge_contexts': []}
BUILD = Path(__file__).resolve().parents[3] / 'build'
original_drop = file_actions.drop_references
original_transfer = file_actions.transfer
original_pending = icon_cache.pending


def observed_drop(target, paths, origin, copy=False):
    # Observation only: the native NodeDrop bridge must supply the actual paths.
    state['drops'].append({'target': target.name, 'paths': list(paths), 'copy': copy})
    context = bpy.context
    state['bridge_contexts'].append({'window': context.window.as_pointer(),
        'hwnd': context.window.blui_native_handle, 'tree': target.name,
        'region': (context.region.x, context.region.y, context.region.width, context.region.height),
        'origin': tuple(origin), 'copy': copy})
    print('NATIVE DROP BRIDGE', state['bridge_contexts'][-1], flush=True)
    return original_drop(target, paths, origin, copy=copy)


def observed_transfer(tree, paths, target, move=False, from_clipboard=False):
    state['transfers'].append({'paths': list(paths), 'directory': target, 'move': move})
    return original_transfer(tree, paths, target, move, from_clipboard)


def own_window(key):
    pointer = state[key]
    result = next((window for window in bpy.context.window_manager.windows
                   if window.as_pointer() == pointer), None)
    assert result is not None, 'QA native window was unexpectedly closed'
    return result


def own_area(key):
    window = own_window(key)
    result = next((area for area in window.screen.areas if area.type == 'NODE_EDITOR'), None)
    assert result is not None, 'QA window no longer contains its desktop editor'
    return result


def tree(key):
    result = own_area(key).spaces.active.edit_tree or own_area(key).spaces.active.node_tree
    assert result and result.bl_idname == model.TREE
    return result


def override(key):
    window, area = own_window(key), own_area(key)
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=area, region=region)


def select(key, paths):
    paths = set(map(str, paths))
    selected = []
    for node in tree(key).nodes:
        node.select = node.bl_idname == model.FILE and node.filepath in paths
        if node.select:
            selected.append(node)
    assert len(selected) == len(paths), 'Fixture file references are missing'
    tree(key).nodes.active = selected[0]
    return selected


def event(key, kind, value, point, *, ctrl=False):
    # Explicit modifiers prevent Ctrl from leaking between the copy/move phases.
    own_window(key).event_simulate(type=kind, value=value, x=round(point[0]), y=round(point[1]),
                                   ctrl=ctrl, shift=False, alt=False, oskey=False)


def icon_point(key, path):
    area = own_area(key)
    region = next(region for region in area.regions if region.type == 'WINDOW')
    node = next(node for node in tree(key).nodes if node.bl_idname == model.FILE and node.filepath == str(path))
    assert node.dimensions.x > 0 and node.dimensions.y > 0, 'Native icon has not been drawn'
    scale = node.dimensions.x / node.width
    location = file_actions.absolute_location(node)
    # The actual native template_icon is below the invisible node header and
    # above its label. Its centre is inside this card's native measured bounds.
    x, y = region.view2d.view_to_region(location[0] * scale + node.dimensions.x * .5,
                                      location[1] * scale - node.dimensions.y * .52, clip=False)
    assert 12 < x < region.width - 12 and 12 < y < region.height - 12, 'Icon lies outside fixture viewport'
    return (region.x + x, region.y + y)


def empty_point(key):
    area = own_area(key)
    region = next(region for region in area.regions if region.type == 'WINDOW')
    # Destination is empty during both cross-window reference phases.
    return (region.x + region.width // 2, region.y + region.height // 2)


def client_geometry(key):
    window = own_window(key)
    handle = int(window.blui_native_handle)
    # This helper revalidates PID/class/native lifetime before reading the HWND.
    window_placement.bounds(handle)
    user = window_placement._api()
    user.GetClientRect.argtypes, user.GetClientRect.restype = [w.HWND, c.POINTER(w.RECT)], w.BOOL
    user.ClientToScreen.argtypes, user.ClientToScreen.restype = [w.HWND, c.POINTER(w.POINT)], w.BOOL
    rectangle, origin = w.RECT(), w.POINT(0, 0)
    assert user.GetClientRect(handle, c.byref(rectangle)) and user.ClientToScreen(handle, c.byref(origin))
    width, height = rectangle.right - rectangle.left, rectangle.bottom - rectangle.top
    assert width > 0 and height > 0
    return origin.x, origin.y, width, height


def other_window_point(source_key, target_key, target_point):
    """Convert physical desktop pixels to the source event's bottom-up pixels."""
    source, target = own_window(source_key), own_window(target_key)
    sx, sy, sw, sh = client_geometry(source_key)
    tx, ty, tw, th = client_geometry(target_key)
    screen_x = tx + target_point[0] * tw / target.width
    screen_y = ty + (target.height - 1 - target_point[1]) * th / target.height
    return (round((screen_x - sx) * source.width / sw),
            round(source.height - 1 - (screen_y - sy) * source.height / sh))


def target_window_hit(key, point):
    """Verify OS Z-order at the explicit point, without moving the real cursor."""
    window = own_window(key)
    left, top, width, height = client_geometry(key)
    physical = w.POINT(round(left + point[0] * width / window.width),
                       round(top + (window.height - 1 - point[1]) * height / window.height))
    user = window_placement._api()
    user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [w.POINT], w.HWND
    user.GetAncestor.argtypes, user.GetAncestor.restype = [w.HWND, w.UINT], w.HWND
    handle = user.GetAncestor(user.WindowFromPoint(physical), 2)
    result = {'expected_hwnd': window.blui_native_handle, 'hit_hwnd': str(handle),
              'physical': (physical.x, physical.y), 'event_local': tuple(point), 'tree': tree(key).name}
    print('NATIVE TARGET HIT', result, flush=True)
    assert handle == int(window.blui_native_handle), 'Target point is obscured or placement is stale'
    return result


def disk_unchanged():
    for index, path in enumerate(source_files):
        assert path.read_text(encoding='utf-8') == 'owned native drag fixture ' + str(index)


def arrange_windows(snapshot):
    rows = snapshot['monitors']
    display = next((row for row in rows if row['primary']), rows[0])
    left, top, right, bottom = display['work']
    assert right - left >= 1000 and bottom - top >= 500, 'QA requires a work area of at least 1000 by 500 pixels'
    margin, gap = 12, 18
    half = (right - left - margin * 2 - gap) // 2
    rectangles = ((left + margin, top + margin, left + margin + half, bottom - margin),
                  (left + margin + half + gap, top + margin, right - margin, bottom - margin))
    for key, rectangle in zip(('source', 'target'), rectangles):
        handle = int(own_window(key).blui_native_handle)
        window_placement.bounds(handle)
        user = window_placement._api()
        assert window_placement.place(handle, list(rectangle), snapshot, preferred=display['device'])
        # Keep owned fixture windows above unrelated windows without activating
        # any other process or changing a foreign HWND's placement.
        window_placement.bounds(handle)
        assert user.SetWindowPos(handle, None, 0, 0, 0, 0, 0x13)
    state['rectangles'] = rectangles


def begin_drag(key, paths, *, ctrl=False):
    assert not bpy.context.window_manager.blui_has_path_drag
    assert file_actions._drag is None, 'A previous native drag was not cleared'
    select(key, paths)
    point = icon_point(key, paths[0])
    state['drag_key'], state['drag_paths'], state['ctrl'] = key, list(map(str, paths)), ctrl
    state['press'] = point
    event(key, 'MOUSEMOVE', 'NOTHING', point, ctrl=ctrl)


def frame_drawn_icons(key, marker):
    """Frame only measured native bounds, then let View2D redraw before hit tests."""
    if not state.get(marker):
        if any(node.dimensions.x <= 0 or node.dimensions.y <= 0 for node in tree(key).nodes):
            own_area(key).tag_redraw()
            return False
        with override(key):
            bpy.ops.node.view_all()
        own_area(key).tag_redraw()
        state[marker] = time.monotonic()
        return False
    return time.monotonic() - state[marker] >= .3


def assert_native_drag():
    assert bpy.context.window_manager.blui_has_path_drag, 'template_icon failed to create native WM_DRAG_PATH'
    captured = file_actions._drag
    assert captured is not None, 'Native drag creation did not capture source canvas identity'
    assert captured['paths'] == state['drag_paths'], (captured['paths'], state['drag_paths'])
    assert len(captured['ids']) == len(state['drag_paths'])
    assert runtime.resolve_tree(captured['token']) == tree(state['drag_key'])


def release_at(source_key, target_key, target_point):
    point = target_point if source_key == target_key else other_window_point(source_key, target_key, target_point)
    assert_native_drag()
    state['target_hit'] = target_window_hit(target_key, target_point)
    state['source_event_point'] = point
    state['drop_key'], state['drop_point'] = target_key, target_point
    event(source_key, 'MOUSEMOVE', 'NOTHING', point, ctrl=state['ctrl'])
    if source_key != target_key:
        # event_simulate directly fills one window's WM queue and intentionally
        # does not execute the GHOST input router. Real GHOST cursor movement
        # sends source/outside AND target/local moves; mouse-up is routed only
        # to the target. Reproduce that documented queue distribution here.
        # WindowFromPoint uses the explicit coordinates, not GetCursorPos.
        event(target_key, 'MOUSEMOVE', 'NOTHING', target_point, ctrl=state['ctrl'])


def step():
    if time.monotonic() - state['started'] > 80:
        raise TimeoutError('Native desktop icon drag regression timed out')
    phase, delay = state['phase'], .22
    if phase == 0:
        space_filebrowser_shell.unregister()
        if bpy.app.timers.is_registered(runtime.tick):
            bpy.app.timers.unregister(runtime.tick)
        runtime._last_tasks = runtime._last_monitors = float('inf')
        icon_cache.pending = lambda: []  # Native built-in fallback remains a real path drag source.
        file_actions.drop_references, file_actions.transfer = observed_drop, observed_transfer
        # Leave the factory main window (which may initially be maximized) in
        # the background. Test with two newly created normal native windows,
        # so initial startup maximize/restore messages cannot resize a source
        # window after placement and cover the intended drop target.
        main = bpy.context.window_manager.windows[0]
        main_area = max(main.screen.areas, key=lambda area: area.width * area.height)
        main_region = next(region for region in main_area.regions if region.type == 'WINDOW')
        with bpy.context.temp_override(window=main, area=main_area, region=main_region):
            source = blui_desktop._new_window(bpy.context)
        state['factory_main'] = main.as_pointer()
        area = max(source.screen.areas, key=lambda area: area.width * area.height)
        region = next(region for region in area.regions if region.type == 'WINDOW')
        with bpy.context.temp_override(window=source, area=area, region=region):
            current = blui_desktop._initialize(area, str(folder))
        state['source'] = source.as_pointer()
        runtime.cancel_pending()
        current.nodes.clear()
        for index, path in enumerate(source_files):
            node = current.nodes.new(model.FILE)
            node.filepath, node.label, node.location = str(path), path.name, (index * 170, 0)
        with override('source'):
            target = blui_desktop._new_window(bpy.context)
        target_area = max(target.screen.areas, key=lambda area: area.width * area.height)
        target_region = next(region for region in target_area.regions if region.type == 'WINDOW')
        with bpy.context.temp_override(window=target, area=target_area, region=target_region):
            target_tree = blui_desktop._initialize(target_area, str(folder))
        state['target'] = target.as_pointer()
        runtime.cancel_pending()
        target_tree.nodes.clear()
        runtime.submit('monitors')  # Enumeration occurs in an isolated desktop worker.
        delay = .4
    elif phase == 1:
        runtime.tick()
        if runtime._jobs:
            return .1
        snapshot = runtime.monitor_snapshot()
        assert snapshot['monitors'], 'Physical display enumeration returned no connected monitors'
        if not state.get('restore_requested'):
            for key in ('source', 'target'):
                handle = int(own_window(key).blui_native_handle)
                window_placement.bounds(handle)
                # ShowWindowAsync and ASYNCWINDOWPOS must not be queued back to
                # back: the restore request may otherwise win after placement.
                assert window_placement._api().ShowWindowAsync(handle, 9)
            state['restore_requested'] = time.monotonic()
            return .5
        if time.monotonic() - state['restore_requested'] < .5:
            return .1
        arrange_windows(snapshot)
        delay = .6
    elif phase == 2:
        assert tree('source') != tree('target'), 'Owned windows unexpectedly share one canvas'
        state['window_diagnostics'] = {key: {'pointer': own_window(key).as_pointer(),
            'hwnd': own_window(key).blui_native_handle, 'tree': tree(key).name,
            'tree_pointer': tree(key).as_pointer(), 'client': client_geometry(key),
            'wm_geometry': (own_window(key).x, own_window(key).y,
                            own_window(key).width, own_window(key).height)}
            for key in ('source', 'target')}
        print('NATIVE WINDOW GEOMETRY', state['window_diagnostics'], flush=True)
        with override('source'):
            bpy.ops.node.view_all()
        begin_drag('source', source_files, ctrl=True)
    elif phase in (3, 9, 15, 23):
        event(state['drag_key'], 'LEFTMOUSE', 'PRESS', state['press'], ctrl=state['ctrl'])
    elif phase in (4, 10, 16, 24):
        # Separate PRESS and MOVE timer frames are intentional: native UI must
        # enter WAIT_DRAG before crossing its normal drag threshold.
        point = (state['press'][0] + 14, state['press'][1] + 2)
        event(state['drag_key'], 'MOUSEMOVE', 'NOTHING', point, ctrl=state['ctrl'])
    elif phase in (5, 11):
        assert_native_drag()
        assert len(state['drag_paths']) == 2, 'Cross-window fixture must retain native multi-selection'
        if phase == 5:
            with override('source'):
                bpy.ops.screen.screenshot(filepath=str(BUILD / 'desktop-native-drag-active.png'))
        release_at('source', 'target', empty_point('target'))
    elif phase in (6, 12, 18, 26):
        assert_native_drag()
        event(state['drop_key'], 'LEFTMOUSE', 'RELEASE', state['drop_point'], ctrl=state['ctrl'])
        delay = .4
    elif phase == 7:
        assert not bpy.context.window_manager.blui_has_path_drag and file_actions._drag is None
        assert state['drops'][-1] == {'target': tree('target').name, 'paths': list(map(str, source_files)), 'copy': True}
        assert len(tree('source').nodes) == len(tree('target').nodes) == 2
        disk_unchanged()
        print('PASS native template_icon multi-path drag -> cross-window Ctrl-copy references; disk unchanged', flush=True)
        tree('target').nodes.clear()
        # Avoid the next mouse press becoming a native double-click.
        delay = .6
    elif phase == 8:
        begin_drag('source', source_files, ctrl=False)
    elif phase == 13:
        assert not bpy.context.window_manager.blui_has_path_drag and file_actions._drag is None
        assert state['drops'][-1] == {'target': tree('target').name, 'paths': list(map(str, source_files)), 'copy': False}
        assert not tree('source').nodes and len(tree('target').nodes) == 2
        disk_unchanged()
        print('PASS native cross-window default drop moves both references, not their real files', flush=True)
        for index, node in enumerate(tree('target').nodes):
            node.location = (index * 170, 0)
        target_node = tree('target').nodes.new(model.FILE)
        target_node.filepath, target_node.label, target_node.folder = str(destination), 'TargetFolder', True
        target_node.location = (400, -180)
        with override('target'):
            bpy.ops.node.view_all()
        delay = .6
    elif phase == 14:
        # The Folder node was just allocated in phase 13. The first view_all
        # there may not include its unmeasured (zero-size) native bounds.
        if not frame_drawn_icons('target', 'folder_framed'):
            return .15
        begin_drag('target', [source_files[1]])
    elif phase == 17:
        assert_native_drag()
        release_at('target', 'target', icon_point('target', destination))
    elif phase == 19:
        runtime.tick()
        if blui_file._jobs or runtime._jobs or runtime._ready:
            return .1
        assert not bpy.context.window_manager.blui_has_path_drag and file_actions._drag is None
        assert state['transfers'][-1] == {'paths': [str(source_files[1])], 'directory': str(destination), 'move': True}
        moved = destination / source_files[1].name
        assert not source_files[1].exists() and moved.read_text(encoding='utf-8') == 'owned native drag fixture 1'
        assert source_files[0].read_text(encoding='utf-8') == 'owned native drag fixture 0'
        assert any(node.filepath == str(moved) for node in tree('target').nodes)
        print('PASS native folder hover/drop routes only the selected file through the protected FIFO move', flush=True)
        (destination / source_files[0].name).write_text('owned collision sentinel', encoding='utf-8')
        delay = .6
    elif phase == 20:
        # The FIFO completion can add/retarget references. Wait for that native
        # layout and the subsequent framing redraw before the collision drag.
        if not frame_drawn_icons('target', 'collision_framed'):
            return .15
    elif phase == 21:
        begin_drag('target', [source_files[0]])
        # State uses a gap so layout redraw cannot race native icon geometry.
        state['phase'] = 23
        return .22
    elif phase == 25:
        assert_native_drag()
        release_at('target', 'target', icon_point('target', destination))
    elif phase == 27:
        runtime.tick()
        if blui_file._jobs or runtime._jobs or runtime._ready:
            return .1
        assert state['transfers'][-1] == {'paths': [str(source_files[0])], 'directory': str(destination), 'move': True}
        assert source_files[0].read_text(encoding='utf-8') == 'owned native drag fixture 0'
        assert (destination / source_files[0].name).read_text(encoding='utf-8') == 'owned collision sentinel'
        assert not blui_file._status[1], 'Collision must be reported as a failed file task'
        assert not bpy.context.window_manager.blui_has_path_drag and file_actions._drag is None
        event('target', 'ESC', 'PRESS', state['drop_point'])
        event('target', 'ESC', 'RELEASE', state['drop_point'])
        print('PASS same-name native folder drop rejects overwrite and retains source file/reference', flush=True)
    else:
        file_actions.drop_references, file_actions.transfer = original_drop, original_transfer
        icon_cache.pending = original_pending
        runtime.unregister()
        fixture.cleanup()
        print('check_desktop_native_drag: PASS', flush=True)
        sys.stdout.flush()
        os._exit(0)
    state['phase'] += 1
    return delay


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        print('NATIVE DRAG DIAGNOSTICS', state, flush=True)
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.5)
