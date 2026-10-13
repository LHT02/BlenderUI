# SPDX-License-Identifier: GPL-2.0-or-later
"""PRIMARY AGENT ONLY: opt-in, serial, disposable desktop-host native QA.

Requires BLUI_DESKTOP_QA_ENABLE=1, isolated CONFIG, --factory-startup and a fresh
own BLUI process. Temporarily changes only original desktop ListView visibility
and parents this fixture's DESKTOP HWNDs. Never kills/restarts Explorer, hides
DefView/WorkerW, changes wallpaper/registry or sends Win+D to user applications.
Only the exact helper process created here is terminated in the recovery phase.
Incompatible DPI is a tested fail-closed result, NOT a successful rendering test.
Do not remove unresolved journal or terminate a recovery guardian on failure.
"""
import ctypes as c
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
import bpy
from blui_desktop import desktop_host, desktop_host_native, monitors, runtime, session
from blui_desktop import native_windows
from blui_desktop.desktop_host_state import Journal
from bl_operators.blui_desktop import _initialize

assert os.environ.get('BLUI_DESKTOP_QA_ENABLE') == '1', 'Explicit desktop takeover QA opt-in required'
session.disable_for_tests = True
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
temporary = tempfile.TemporaryDirectory(prefix='blui_desktop_host_native_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
started = time.monotonic()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_desktop_dpi import DesktopDpiQA
dpi_qa = DesktopDpiQA()
backend, original, snapshot = dpi_qa.discovery()
original_list_visible = original['visible']
normal_tokens = {(window.as_pointer(), window.blui_native_handle)
                 for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL'}
controller = desktop_host.Controller(temporary.name)
state = {'phase': 0, 'due': 0., 'surfaces': [], 'tokens': [], 'serial': 0,
         'helper': None, 'helper_started': '', 'error': '', 'cleaning': False,
         'passed': False, 'dpi_skip': False}
print('desktop QA baseline:', {'visible': original_list_visible, 'host': original['host'],
                               'raised': original['raised'], 'monitors': snapshot}, flush=True)
diagnostics = {'key': None, 'at': 0.}


def fresh(token):
    window = next((window for window in bpy.context.window_manager.windows
                   if (window.as_pointer(), window.blui_native_handle) == token), None)
    if window is None:
        return None
    assert window.blui_shell_role == 'DESKTOP', 'Owned desktop role changed'
    identity = native_windows._identity(backend.user, int(window.blui_native_handle))
    assert identity and identity[0] == os.getpid(), 'Only own fixture DESKTOP HWNDs may be touched'
    return window


def original_restored():
    assert backend.matches_shell(original), 'Explorer desktop changed during QA; no stale writes permitted'
    return bool(backend.user.IsWindowVisible(int(original['list']['handle']))) == original_list_visible


def create_surfaces():
    for display in snapshot['monitors']:
        before = {window.as_pointer() for window in bpy.context.window_manager.windows}
        dpi_qa.unchanged()
        assert bpy.ops.wm.blui_shell_window_create(role='DESKTOP', width=800, height=600) == {'FINISHED'}
        dpi_qa.unchanged()
        new = [window for window in bpy.context.window_manager.windows if window.as_pointer() not in before]
        assert len(new) == 1 and new[0].blui_shell_role == 'DESKTOP'
        window = new[0]
        handle = int(window.blui_native_handle)
        dpi_qa.compatible(handle, int(original['host']['handle']))
        assert backend.user.GetPropW(handle, desktop_host_native.MARKER) == 1
        instance = backend.user.GetPropW(handle, desktop_host_native.INSTANCE)
        assert instance and 0 < instance < 1 << (c.sizeof(c.c_void_p) * 8)
        child_dpi = backend.user.GetWindowDpiAwarenessContext(handle)
        parent_dpi = backend.user.GetWindowDpiAwarenessContext(int(original['host']['handle']))
        print('desktop QA new source:', {'handle': str(handle), 'instance': instance,
              'child_dpi': child_dpi, 'host_dpi': parent_dpi,
              'equal': bool(backend.user.AreDpiAwarenessContextsEqual(child_dpi, parent_dpi))}, flush=True)
        area = max(window.screen.areas, key=lambda area: area.width * area.height)
        assert area.type == 'NODE_EDITOR', 'DESKTOP native layout must be Node Editor, not INFO'
        _initialize(area, temporary.name)  # Empty OWN fixture directory; no system apps/files launched.
        area.spaces.active.node_tree.monitor = display['device']
        state['tokens'].append((window.as_pointer(), window.blui_native_handle))
        state['surfaces'].append({'handle': window.blui_native_handle,
                                  'device': display['device'], 'rect': display['work']})


def check_attached(status):
    assert status['enabled'] and status['attached_count'] == len(state['tokens'])
    assert set(status['handles']) == {token[1] for token in state['tokens']}
    for token in state['tokens']:
        window = fresh(token)
        assert window is not None
        handle = int(window.blui_native_handle)
        assert backend.user.GetParent(handle) == int(original['host']['handle'])
        assert backend.user.GetWindowLongPtrW(handle, -16) & desktop_host_native.WS_CHILD
        assert not backend.user.GetWindowLongPtrW(handle, -20) & 0x8, 'Desktop must never be global TOPMOST'
    assert not backend.user.IsWindowVisible(int(original['list']['handle'])) or not original_list_visible
    assert {(window.as_pointer(), window.blui_native_handle)
            for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL'} == normal_tokens


def cleanup(error=''):
    if error:
        state['error'] = error
    state['cleaning'] = True
    # Controller can be stopped after the crash phase; same-directory restart is
    # intentionally deferred until the recovery witness releases its lock.
    if not controller._stopping.is_set():
        state['serial'] = controller.request('restore')
    else:
        state['serial'] = 0


def close_owned():
    for token in state['tokens']:
        window = fresh(token)
        if window is None:
            continue
        with bpy.context.temp_override(window=window):
            assert bpy.ops.wm.window_close(force_close=True) == {'FINISHED'}
    controller.close()


def finish(code):
    if not code:
        journal = Journal(temporary.name).read()
        assert original_restored()
        assert journal is None or (journal['shell'] is None and not journal['canvases'])
    temporary._finalizer.detach()  # Do not race the independent guardian's final atomic journal write.
    print('Desktop QA artifacts retained; restoration ' +
          ('pending/failed:' if code else 'verified:'), temporary.name, flush=True)
    os._exit(code)


def tick():
    try:
        now = time.monotonic()
        status = controller.tick()
        process = controller.process
        diagnostic = {'phase': state['phase'], 'cleaning': state['cleaning'],
                      'issued': state['serial'], 'status': status,
                      'pid': process.pid if process else None,
                      'poll': process.poll() if process else None,
                      'stopped': controller._stopping.is_set()}
        key = repr(diagnostic)
        if key != diagnostics['key'] or now - diagnostics['at'] >= 2:
            print('desktop QA progress:', diagnostic, flush=True)
            if status.get('pending_restore'):
                rollback = Journal(temporary.name).read()
                for row in rollback['canvases'] if rollback else []:
                    if not backend.canvas_matches(row):
                        continue  # Snapshot only exact OWN PID/start/class/instance, no reused HWND.
                    handle = int(row['window']['handle'])
                    parent = backend.user.GetParent(handle)
                    print('desktop QA rollback:', {'handle': str(handle), 'parent': parent,
                        'desktop_parent': backend.user.GetDesktopWindow(),
                        'style': backend.user.GetWindowLongPtrW(handle, -16) & 0xffffffff,
                        'saved_style': row['style'],
                        'extended_style': backend.user.GetWindowLongPtrW(handle, -20) & 0xffffffff,
                        'saved_extended_style': row['extended_style'],
                        'owner': backend.user.GetWindow(handle, 4), 'saved_owner': row['owner'],
                        'rect': backend._rect(handle), 'saved_rect': row['rect']}, flush=True)
            diagnostics.update(key=key, at=now)
        if now - started > 50:
            raise RuntimeError('Desktop native QA timed out')
        if state['cleaning']:
            acknowledged = state['serial'] == 0 or status['completed_serial'] >= state['serial']
            restored = not status['pending_restore']
            if state['serial'] == 0:
                # A dead helper cannot publish its guardian's final status. Use
                # the exact own journal plus physical checks, never stale RAM.
                value = Journal(temporary.name).read()
                restored = bool(value and not value['shell'] and not value['canvases'])
            if acknowledged and restored and original_restored():
                close_owned()
                process = controller.process
                if process is not None and process.poll() is None:
                    return .1
                if state['error']:
                    print('check_desktop_host_native: FAIL', state['error'], flush=True)
                    finish(1)
                print('check_desktop_host_native: PASS' +
                      (' (DPI mismatch fail-closed; no actual parenting/rendering asserted)' if state['dpi_skip'] else
                       ' (all-display native attachment, exact ack, normal restore and own-helper crash recovery)'), flush=True)
                finish(0)
            return .1
        phase = state['phase']
        if phase == 0:
            assert snapshot['monitors']
            create_surfaces()
            state['serial'] = controller.request('reconcile', state['surfaces'])
            state['phase'] = 1
        elif phase == 1:
            if status['completed_serial'] < state['serial']:
                if status['error'] and controller._stopping.is_set():
                    raise RuntimeError(status['error'])
                return .1
            if not status['enabled']:
                if 'DPI awareness differ' in status['error']:
                    assert original_restored() and not status['pending_restore']
                    state['dpi_skip'], state['passed'] = True, True
                    cleanup()
                    return .1
                raise RuntimeError(status['error'] or 'Desktop attachment did not enable')
            check_attached(status)
            state['serial'] = controller.request('restore')
            state['phase'] = 2
        elif phase == 2:
            if status['completed_serial'] < state['serial'] or status['pending_restore']:
                return .1
            assert not status['enabled'] and original_restored()
            for token in state['tokens']:
                window = fresh(token)
                assert window is not None
                assert not backend.user.GetWindowLongPtrW(int(window.blui_native_handle), -16) & desktop_host_native.WS_CHILD
            state['serial'] = controller.request('reconcile', state['surfaces'])
            state['phase'] = 3
        elif phase == 3:
            if status['completed_serial'] < state['serial']:
                return .1
            check_attached(status)
            process = controller.process
            assert process and process.poll() is None and process.pid != os.getpid()
            child_started = native_windows._process_start(process.pid)
            assert child_started, 'Own helper immutable kernel identity is required'
            state['helper'], state['helper_started'] = process, child_started
            assert controller.process is process and native_windows._process_start(process.pid) == child_started
            process.terminate()  # ONLY this exact fixture-created child, never Explorer/other BLUI.
            state['phase'], state['due'] = 4, now + 10
        else:
            if not original_restored():
                assert now < state['due'], 'Own-helper crash did not restore original icons'
                return .1
            for token in state['tokens']:
                window = fresh(token)
                if window is not None and backend.user.GetWindowLongPtrW(int(window.blui_native_handle), -16) & desktop_host_native.WS_CHILD:
                    assert now < state['due'], 'Own-helper crash did not detach surviving canvases'
                    return .1
            state['passed'] = True
            print('desktop QA crash recovered:', Journal(temporary.name).read(), flush=True)
            # The dead helper's controller may not yet have observed EOF. Do
            # not enqueue restore into a dead stdin and then await its impossible
            # ack; the second guardian's exact journal is the completion signal.
            state['serial'] = 0
            state['cleaning'] = True
        return .1
    except Exception:
        traceback.print_exc()
        if state['cleaning']:
            controller.close()
            finish(1)
        cleanup('Native desktop QA failed; see traceback')
        return .1


bpy.app.timers.register(tick, first_interval=.5)
