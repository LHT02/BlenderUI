# SPDX-License-Identifier: GPL-2.0-or-later
"""Native desktop v2 integration, owned fixture/windows/config only.

Run sequentially after building:
  BLUI.exe --factory-startup --enable-event-simulate --python-exit-code 1 --python <this script>
No network, clipboard mutation, system-taskbar visibility change, foreign-window
activation/closure, or user CONFIG access is required. Physical hotplug is not
simulated; two owned native windows exercise cross-display board references.
"""
import copy
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import zlib

import bpy
from bl_operators import blui_desktop
from bl_ui import space_filebrowser_shell
from blui_desktop import background, boards, file_actions, groups, model, runtime, serialization, session

fixture = tempfile.TemporaryDirectory(prefix='blui_desktop_integration_')
folder = Path(fixture.name)
os.environ['BLUI_DESKTOP_CONFIG'] = str(folder / 'config')
session.disable_for_tests = True
paths = []
for name in ('parent-a.txt', 'parent-b.txt', 'group-file.txt'):
    path = folder / name
    path.write_text('owned reference fixture: ' + name, encoding='utf-8')
    paths.append(str(path))


def chunk(kind, content):
    return struct.pack('>I', len(content)) + kind + content + struct.pack('>I', zlib.crc32(kind + content))


png = folder / 'transparent.png'
png.write_bytes(b'\x89PNG\r\n\x1a\n' +
    chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0)) +
    chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00\xff\x00\xff\x00\x00'
                               b'\x00\x00\x00\xff\x80\xff\xff\xff\xff')) + chunk(b'IEND', b''))
state = {'phase': 0, 'started': time.monotonic()}


def owned_window():
    return bpy.context.window_manager.windows[0]


def area():
    return owned_window().screen.areas[0]


def tree():
    result = bpy.data.node_groups.get(state['root'])
    assert result is not None
    return result


def override(editor=None, window=None):
    editor, window = editor or area(), window or owned_window()
    region = next(region for region in editor.regions if region.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=editor, region=region)


def absolute(node):
    result = node.location.copy()
    parent = node.parent
    for _depth in range(16):
        if not parent:
            return result
        result += parent.location
        parent = parent.parent
    raise AssertionError('Fixture frame hierarchy unexpectedly recursive')


def select(nodes, active=None):
    current = area().spaces.active.edit_tree or area().spaces.active.node_tree
    for node in current.nodes:
        node.select = node in nodes
    current.nodes.active = active or nodes[0]


def prepare(path):
    with override():
        assert bpy.ops.wm.blui_canvas_drag_prepare(filepath=path) == {'FINISHED'}


def assert_disk_unchanged():
    for path in paths:
        assert Path(path).read_text(encoding='utf-8') == 'owned reference fixture: ' + Path(path).name


def assert_snapshot(current, expected, label):
    actual = serialization.snapshot(current)
    if actual != expected:
        changes = []
        def compare(before, after, path='$'):
            if before == after:
                return
            if isinstance(before, dict) and isinstance(after, dict):
                for key in sorted(before.keys() | after.keys()):
                    if key not in before or key not in after:
                        changes.append({'path': path + '.' + key,
                                        'before': before.get(key, '<missing>'),
                                        'after': after.get(key, '<missing>')})
                    else:
                        compare(before[key], after[key], path + '.' + key)
            elif isinstance(before, list) and isinstance(after, list):
                if len(before) != len(after):
                    changes.append({'path': path + '.length', 'before': len(before), 'after': len(after)})
                for index, (old, new) in enumerate(zip(before, after)):
                    compare(old, new, path + '[' + str(index) + ']')
            else:
                changes.append({'path': path, 'before': before, 'after': after})
        compare(expected, actual)
        print(label + ' snapshot differences: ' + json.dumps(changes, ensure_ascii=False), flush=True)
        print(label + ' snapshot before: ' + json.dumps(expected, ensure_ascii=False), flush=True)
        print(label + ' snapshot after: ' + json.dumps(actual, ensure_ascii=False), flush=True)
    assert actual == expected, label + ' changed persisted desktop graph fields'


def step():
    if time.monotonic() - state['started'] > 70:
        raise TimeoutError('Desktop v2 integration timed out')
    phase, delay = state['phase'], .25
    if phase == 0:
        space_filebrowser_shell.unregister()
        if bpy.app.timers.is_registered(runtime.tick):
            bpy.app.timers.unregister(runtime.tick)
        runtime._last_tasks = runtime._last_monitors = float('inf')
        runtime.layout_path = lambda _tree: str(folder / 'manual-layout.json')
        # Factory fixture only; never change the edit mode in an existing user window.
        active = owned_window().view_layer.objects.active
        if active and active.mode != 'OBJECT':
            with override():
                assert bpy.ops.object.mode_set(mode='OBJECT') == {'FINISHED'}
        with override():
            current = blui_desktop._initialize(area(), str(folder))
        runtime.cancel_pending()
        current.nodes.clear()
        state['root'] = current.name
        bpy.context.preferences.edit.use_global_undo = True
        first_frame = current.nodes.new(model.FRAME)
        first_frame.label, first_frame.location = 'Panel A', (300, 120)
        first_frame.shrink = False
        second_frame = current.nodes.new(model.FRAME)
        second_frame.label, second_frame.location = 'Panel B', (-300, -180)
        second_frame.shrink = False
        for index, parent in enumerate((first_frame, second_frame)):
            node = current.nodes.new(model.FILE)
            node.filepath, node.label, node.parent = paths[index], Path(paths[index]).name, parent
            node.location = (40, -50)
        clock = current.nodes.new(model.CLOCK)
        clock.location, clock.clock_format, clock.date_format = (600, 250), '%H:%M', '%A'
        calc = current.nodes.new(model.CALCULATOR)
        calc.expression, calc.location = 'sqrt(16)+2**3', (600, -80)
        assert calc.result == '12', calc.result
        weather = current.nodes.new(model.WEATHER)
        weather.city, weather.weather_enabled = '深圳', False
        weather.latitude, weather.longitude, weather.location = 22.54, 114.06, (900, 250)
        note = current.nodes.new(model.NOTE)
        note.note, note.location = 'Native save/restore sentinel', (-600, 250)
        with override():
            bpy.ops.node.view_all()
            bpy.ops.ed.undo_push(message='Desktop integration owned fixture')
        delay = .4
    elif phase == 1:
        current = tree()
        payload = serialization.snapshot(current)
        state['snapshot'] = copy.deepcopy(payload)
        serialization.apply(current, payload)
        assert_snapshot(current, payload, 'Frame/widget recovery')
        assert all(node.parent for node in current.nodes if node.bl_idname == model.FILE)
        assert next(node for node in current.nodes if node.bl_idname == model.CALCULATOR).result == '12'
        print('PASS native Frame parents, stable IDs and clock/calculator/offline-weather settings restore', flush=True)
        # A real native Make Group must enter a real child tree, not a fake frame.
        note = next(node for node in current.nodes if node.bl_idname == model.NOTE)
        group_file = current.nodes.new(model.FILE)
        group_file.filepath, group_file.label = paths[2], Path(paths[2]).name
        select([note, group_file], group_file)
        with override():
            assert bpy.ops.node.group_make('EXEC_DEFAULT', True) == {'FINISHED'}
        delay = .3
    elif phase == 2:
        current = tree()
        group = next(node for node in current.nodes if node.bl_idname == model.GROUP)
        assert group.node_tree and area().spaces.active.edit_tree == group.node_tree
        assert any(node.bl_idname == model.FILE and node.filepath == paths[2] for node in group.node_tree.nodes)
        with override():
            assert bpy.ops.node.group_edit(exit=True) == {'FINISHED'}
        assert area().spaces.active.edit_tree == current
        # Two native instances share one actual group; portable recovery retains that identity.
        linked = current.nodes.new(model.GROUP)
        linked.node_tree, linked.location = group.node_tree, (120, -350)
        graph = serialization.snapshot(current)
        assert len(graph['groups']) == 1
        serialization.apply(current, graph)
        restored = [node for node in current.nodes if node.bl_idname == model.GROUP]
        assert restored[0].node_tree == restored[1].node_tree
        assert_snapshot(current, graph, 'Native shared-group recovery')
        print('PASS native Group Make/Edit and shared graph recovery preserve real file references', flush=True)
        current.background_path, current.background_enabled = str(png), True
        current.background_fit, current.background_opacity = 'FIT', .6
        # Known stale data must be discarded before any native GPU upload.
        old_generation = current.background_generation
        runtime._ready.append(('background', runtime.identity(current), old_generation,
                               {'must-not-decode': True}, (0, 0), ''))
        current.background_enabled = False
        runtime.tick()
        assert not runtime._ready and not current.background_enabled
        current.background_enabled = True
        runtime.submit('background', current, str(png))
    elif phase == 3:
        runtime.tick()
        if runtime._jobs or runtime._ready:
            return .1
        assert background.has_image(tree()), tree().service_status
        assert tree().background_path == str(png)
        assert abs(tree().background_opacity - .6) < 1e-5
        print('PASS stale wallpaper replies discarded; isolated PNG alpha decoding reaches native draw cache', flush=True)
        # A second native window provides an independent target board. No other process is touched.
        with override():
            new_window = blui_desktop._new_window(bpy.context)
        editor = max(new_window.screen.areas, key=lambda editor: editor.width * editor.height)
        with override(editor, new_window):
            target = blui_desktop._initialize(editor, str(folder))
        runtime.cancel_pending()
        target.nodes.clear()
        state['target'], state['target_window'] = target.name, new_window.as_pointer()
        nodes = [node for node in tree().nodes if node.bl_idname == model.FILE]
        select(nodes)
        state['delta'] = tuple(absolute(nodes[1]) - absolute(nodes[0]))
        prepare(nodes[0].filepath)
        assert file_actions.drop_references(target, [node.filepath for node in nodes], (120, 200), copy=True)
        copied = list(target.nodes)
        assert len(copied) == 2
        assert tuple(copied[1].location - copied[0].location) == state['delta']
        assert len([node for node in tree().nodes if node.bl_idname == model.FILE]) == 2
        assert_disk_unchanged()
        print('PASS cross-window copy keeps both boards and absolute spacing of icons in different Frame panels', flush=True)
    elif phase == 4:
        target = bpy.data.node_groups[state['target']]
        target.nodes.clear()
        nodes = [node for node in tree().nodes if node.bl_idname == model.FILE]
        select(nodes)
        prepare(nodes[0].filepath)
        assert file_actions.drop_references(target, [node.filepath for node in nodes], (-50, 90), copy=False)
        assert not any(node.bl_idname == model.FILE for node in tree().nodes)
        assert tuple(target.nodes[1].location - target.nodes[0].location) == state['delta']
        assert_disk_unchanged()
        print('PASS cross-window move transfers only references; original on-disk files stay unchanged', flush=True)
        # Stale sources must never be removed, even if their underlying paths still match.
        current = tree()
        stale = current.nodes.new(model.FILE)
        stale.filepath, stale.label = paths[0], 'Fresh drag source'
        select([stale])
        prepare(stale.filepath)
        stale.label = 'Edited during drag'
        count = len(target.nodes)
        try:
            file_actions.drop_references(target, [stale.filepath], (0, 0))
        except ValueError:
            pass
        else:
            raise AssertionError('Stale drag was accepted after its source changed')
        assert len(target.nodes) == count and stale in current.nodes[:]
        assert_disk_unchanged()
        print('PASS stale drag source identity/fingerprint rejects destructive reference transfer', flush=True)
        # Use the real asynchronous collection scheduler, but only our redirected config directory.
        session.disable_for_tests, session._loaded = False, True
        session._collection = None
        saved = session.collection()
        state['saved'] = saved
        session.save_now(runtime)
    elif phase == 5:
        session.tick(runtime)
        if session._scheduler.job:
            return .1
        saved_path = Path(session.storage_path())
        assert saved_path.parent == folder / 'config'
        assert saved_path.is_file() and saved_path.with_suffix('.bak').is_file()
        recovered = boards.load(str(saved_path))
        assert len(recovered['boards']) == 2
        assert recovered == state['saved']
        saved_path.write_bytes(b'{owned crash fixture truncated')
        assert boards.load(str(saved_path)) == recovered
        print('PASS asynchronous all-board autosave and first-save backup recover both native displays', flush=True)
        session.disable_for_tests = True
        old_identity = runtime.identity(tree())
        queued = runtime.submit('paths', tree(), [paths[0]])
        runtime.cancel_pending()
        assert queued.closed and runtime.resolve_tree(old_identity) is None
        assert not runtime._jobs and not runtime._ready
        assert_disk_unchanged()
        print('PASS undo/load epoch cancellation prevents late jobs from mutating reused RNA identities', flush=True)
        with override():
            bpy.ops.node.view_all()
        delay = .4
    else:
        if background.has_image(tree()):
            diagnostics = background.diagnostics(tree())
            assert not diagnostics['error'], diagnostics['error']
        with override():
            bpy.ops.screen.screenshot(filepath=str(SOURCE_BUILD / 'desktop-integration.png'))
        runtime.unregister()
        session.disable_for_tests = True
        session.reset(runtime._epoch)
        fixture.cleanup()
        print('check_desktop_integration: PASS', flush=True)
        sys.stdout.flush()
        os._exit(0)
    state['phase'] += 1
    return delay


SOURCE_BUILD = Path(__file__).resolve().parents[3] / 'build'


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.5)
