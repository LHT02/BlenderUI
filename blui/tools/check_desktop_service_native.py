# SPDX-License-Identifier: GPL-2.0-or-later
"""PRIMARY AGENT ONLY: actual explicit desktop UI/service + thumbnail lifecycle QA.

Requires BLUI_DESKTOP_QA_ENABLE=1, factory startup, isolated CONFIG, event simulate.
Temporarily embeds only new OWN DESKTOP windows and hides/restores the recorded
original ListView. No global Win+D, clipboard/file mutation outside own temp
fixtures, Explorer kill/restart, foreign activation or real power action.
"""
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time
import traceback
from unittest import mock
import bpy
from blui_desktop import desktop_host, desktop_host_native, desktop_service, model, paths
from blui_desktop import monitors, power_state, runtime, serialization, session, start_menu_ui, system_power
from blui_desktop import client, taskbar, thumbnail_cache
from blui_desktop.desktop_host_state import Journal

assert os.environ.get('BLUI_DESKTOP_QA_ENABLE') == '1', 'Explicit desktop QA opt-in required'
temporary = tempfile.TemporaryDirectory(prefix='blui_desktop_service_native_qa_')
folder = Path(temporary.name)
icons = folder / 'icons'
icons.mkdir()
os.environ['BLUI_DESKTOP_CONFIG'] = str(folder / 'config')
session.disable_for_tests = True
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_desktop_background import png_rgba
from qa_desktop_dpi import DesktopDpiQA
dummy_paths = []
for name, pixel in (('own-red.png', bytes((255, 30, 30, 255))), ('own-green.png', bytes((30, 255, 30, 128)))):
    target = icons / name
    target.write_bytes(png_rgba(64, 64, pixel * 4096))
    dummy_paths.append(str(target))
directory_patch = mock.patch.object(paths, 'desktop', return_value=str(icons))
directory_patch.start()
forbidden_power = mock.patch.object(system_power, 'hibernate', side_effect=AssertionError('QA never hibernates'))
forbidden_power.start()
dpi_qa = DesktopDpiQA()
backend, original, initial_monitors = dpi_qa.discovery()
runtime._monitors = initial_monitors
desktop_service.tick(initial_monitors)
assert not desktop_service.snapshot()['desired'] and not desktop_service.snapshot()['enabled']
assert desktop_host._controller is None, 'Default service must not spawn a takeover helper'


def normal_shape():
    return {(window.as_pointer(), window.blui_native_handle):
            (window.screen.as_pointer(), window.workspace.name,
             tuple((area.as_pointer(), area.type) for area in window.screen.areas))
            for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL'}


baseline_normal = normal_shape()
assert baseline_normal, 'Owned NORMAL anchor is required'
state = {'phase': 0, 'started': time.monotonic(), 'at': 0., 'last': None,
         'layouts': {}, 'tokens': [], 'error': '', 'cleaning': False, 'restore_serial': 0}
print('desktop service QA baseline:', {'visible': original['visible'], 'normal': list(baseline_normal),
                                     'displays': len(initial_monitors['monitors'])}, flush=True)


class FakeLayout:
    def __init__(self):
        self.operators, self.labels = [], []

    def operator(self, name, **_kwargs):
        row = SimpleNamespace(action='')
        self.operators.append((name, row))
        return row

    def label(self, **kwargs):
        self.labels.append(kwargs.get('text', ''))


def check_conditional_power_menu():
    # Call the actual registered bpy Python Menu.draw, but only record its layout.
    # Operator invocation/execution and actual system capability mutation never run.
    for enabled in (False, True):
        layout = FakeLayout()
        with mock.patch.object(power_state, 'snapshot', return_value={'hibernate': enabled}):
            start_menu_ui.BLUI_MT_start_power.draw(SimpleNamespace(layout=layout), bpy.context)
        actions = [row.action for _name, row in layout.operators]
        assert ('HIBERNATE' in actions) is enabled
        assert {'POWER_SETTINGS', 'LOCK', 'SHUTDOWN', 'RESTART'} <= set(actions)
        assert layout.operator_context == 'INVOKE_DEFAULT'
    layout = FakeLayout()
    start_menu_ui.WM_OT_blui_start_system.draw(SimpleNamespace(layout=layout, action='HIBERNATE'), bpy.context)
    assert len(layout.labels) == 2, 'Hibernate confirmation must include save-work warning'
    print('desktop service QA: actual bpy power Menu.draw conditional + confirmation PASS; zero power calls', flush=True)


def originals_restored():
    assert backend.matches_shell(original), 'Explorer identity/desktop chain changed during own QA'
    return bool(backend.user.IsWindowVisible(int(original['list']['handle']))) == original['visible']


def fresh_desktops():
    result = []
    for token, device in tuple(desktop_service._service.owned.items()):
        window = desktop_service._service.adapter.fresh(token)
        assert window is not None and window.blui_shell_role == 'DESKTOP'
        identity = backend.current(window.blui_native_handle)
        dpi_qa.compatible(int(window.blui_native_handle), int(original['host']['handle']))
        assert identity and identity['pid'] == os.getpid(), 'Only exact OWN DESKTOP windows permitted'
        area = max(window.screen.areas, key=lambda area: area.width * area.height)
        assert area.type == 'NODE_EDITOR' and area.spaces.active.tree_type == model.TREE
        tree = area.spaces.active.node_tree
        assert tree and tree.monitor == device and tree.use_fake_user
        assert backend.user.GetParent(int(window.blui_native_handle)) == int(original['host']['handle'])
        result.append((token, device, tree))
    assert len(result) == len(initial_monitors['monitors'])
    return result  # Local tick only; no RNA stored in persistent state.


def cleanup(error=''):
    state['error'] = error
    state['cleaning'] = True
    try:
        assert bpy.ops.wm.blui_windows_desktop(action='RESTORE') == {'FINISHED'}
        state['restore_serial'] = desktop_service._service.serial
    except Exception:
        desktop_service.shutdown()
        traceback.print_exc()


def finish(code):
    if not code:
        journal = Journal(session.storage_directory()).read()
        assert originals_restored() and not desktop_service._service.owned
        assert journal is None or (journal['shell'] is None and not journal['canvases'])
    desktop_service.shutdown()
    taskbar.close()
    client.close_all()
    directory_patch.stop()
    forbidden_power.stop()
    temporary._finalizer.detach()  # Independent guardians can still publish the empty final journal.
    print('Desktop service QA artifacts retained; restoration ' +
          ('pending/failed:' if code else 'verified:'), temporary.name, flush=True)
    os._exit(code)


def tick():
    try:
        runtime.tick()  # Actual job queue, service lifecycle and fresh-RNA guards.
        dpi_qa.unchanged()
        status = desktop_service.snapshot()
        now = time.monotonic()
        key = repr((state['phase'], status))
        if key != state['last'] or now - state['at'] >= 2:
            print('desktop service QA progress:', {'phase': state['phase'], 'status': status}, flush=True)
            state.update(last=key, at=now)
        if now - state['started'] > 55:
            raise RuntimeError('Desktop service native QA timed out')
        assert normal_shape() == baseline_normal, 'Service must never move/retype/close NORMAL user windows'
        if state['cleaning']:
            if status['phase'] != 'IDLE' or not originals_restored():
                return .1
            assert status['completed_serial'] >= state['restore_serial']
            assert not desktop_service._service.owned
            if state['error']:
                print('check_desktop_service_native: FAIL', state['error'], flush=True)
                finish(1)
            print('check_desktop_service_native: PASS (default unchanged, actual operator/service all-display Native Node embedding, async OWN PNG previews, ack-gated close, NORMAL/layout preserved, conditional Hibernate menu)', flush=True)
            finish(0)
        phase = state['phase']
        if phase == 0:
            check_conditional_power_menu()
            assert originals_restored()
            assert bpy.ops.wm.blui_windows_desktop(action='ENABLE') == {'FINISHED'}
            state['phase'] = 1
        elif phase == 1:
            if status['error'] and not status['desired']:
                raise RuntimeError(status['error'])
            if status['phase'] != 'CONNECTED':
                return .1
            rows = fresh_desktops()
            if any({node.filepath for node in tree.nodes if node.bl_idname == model.FILE} != set(dummy_paths)
                   for _token, _device, tree in rows):
                return .1
            # Native node draw normally queues these; this RAM-only call also
            # guarantees offscreen test cards enter the real isolated queue.
            for path in dummy_paths:
                thumbnail_cache.value(path)
            if any(not thumbnail_cache._entries.get(path, (0,))[0] for path in dummy_paths):
                return .1
            for token, device, tree in rows:
                next(node for node in tree.nodes if node.bl_idname == model.FILE).location = (93, -57)
                state['layouts'][device] = {'board': tree.board_id, 'layout': deepcopy(serialization.snapshot(tree))}
                state['tokens'].append(token)
            assert bpy.ops.wm.blui_windows_desktop(action='RESTORE') == {'FINISHED'}
            state['restore_serial'] = desktop_service._service.serial
            state['phase'] = 2
        elif phase == 2:
            if status['phase'] != 'IDLE':
                return .1
            assert status['completed_serial'] >= state['restore_serial'] and not status['enabled'] and not status['pending_restore']
            assert originals_restored() and not desktop_service._service.owned
            current = {(window.as_pointer(), window.blui_native_handle) for window in bpy.context.window_manager.windows}
            assert not current.intersection(state['tokens']), 'Ack-gated RESTORE must actually close only old OWN sources'
            for record in state['layouts'].values():
                tree = session.by_id(record['board'])
                assert tree is not None and serialization.snapshot(tree) == record['layout'], 'Fake-user layout must survive window closure'
            assert bpy.ops.wm.blui_windows_desktop(action='ENABLE') == {'FINISHED'}
            state['phase'] = 3
        else:
            if status['error'] and not status['desired']:
                raise RuntimeError(status['error'])
            if status['phase'] != 'CONNECTED':
                return .1
            for _token, device, tree in fresh_desktops():
                assert tree.board_id == state['layouts'][device]['board']
                assert serialization.snapshot(tree) == state['layouts'][device]['layout']
            cleanup()
        return .1
    except Exception:
        traceback.print_exc()
        if state['cleaning']:
            finish(1)
        cleanup('See native service traceback')
        return .1


bpy.app.timers.register(tick, first_interval=.5)
