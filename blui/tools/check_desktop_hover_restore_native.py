# SPDX-License-Identifier: GPL-2.0-or-later
"""ROOT ONLY: actual Desktop capture/Node box-modal/idle-hover/RESTORE regression.

Requires BLUI_DESKTOP_QA_ENABLE=1, --factory-startup --enable-event-simulate and
isolated CONFIG. Only fixture-owned DESKTOP HWNDs receive capture or simulated
input. Real service/helper temporarily attach them and restore the recorded
Explorer icon visibility. No foreign activation, global input, process kill,
registry/SPI change, original taskbar hiding or normal-window mutation.
BLUI_DESKTOP_QA_SCREENSHOTS=2 (default), 4 or 8 repeats real nested screenshot
redraws for PYTHONMALLOC=debug GIL regression; it does not disable callbacks.
"""
from copy import deepcopy
import ctypes as c
from ctypes import wintypes as w
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest import mock
import bpy
from blui_desktop import client, desktop_host, desktop_host_native, desktop_service
from blui_desktop import model, monitors, native_windows, paths, runtime, serialization, session, taskbar, widgets
from blui_desktop.desktop_host_state import Journal

assert os.environ.get('BLUI_DESKTOP_QA_ENABLE') == '1', 'Explicit desktop QA opt-in required'


def screenshots_per_phase():
    count = int(os.environ.get('BLUI_DESKTOP_QA_SCREENSHOTS', '2'))
    if count not in (2, 4, 8):
        raise ValueError('BLUI_DESKTOP_QA_SCREENSHOTS must be 2, 4 or 8')
    return count // 2  # Two original screenshot phases; total stays bounded.


_screenshot_repetitions = screenshots_per_phase()
faulthandler.enable(file=sys.stderr, all_threads=True)
faulthandler.dump_traceback_later(20, repeat=True, file=sys.stderr)
temporary = tempfile.TemporaryDirectory(prefix='blui_desktop_hover_restore_qa_')
folder = Path(temporary.name)
icons = folder / 'empty-own-desktop'
icons.mkdir()
os.environ['BLUI_DESKTOP_CONFIG'] = str(folder / 'config')
session.disable_for_tests = True
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
directory_patch = mock.patch.object(paths, 'desktop', return_value=str(icons))
directory_patch.start()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_desktop_dpi import DesktopDpiQA
dpi_qa = DesktopDpiQA()
user = native_windows._api()
for name, result, args in (
    ('GetThreadDpiAwarenessContext', c.c_void_p, []),
    ('SetThreadDpiAwarenessContext', c.c_void_p, [c.c_void_p]),
    ('GetCapture', w.HWND, []), ('SetCapture', w.HWND, [w.HWND]),
    ('ReleaseCapture', w.BOOL, []), ('GetPropW', w.HANDLE, [w.HWND, w.LPCWSTR]),
    ('SetFocus', w.HWND, [w.HWND]), ('GetFocus', w.HWND, []),
    ('GetClientRect', w.BOOL, [w.HWND, c.POINTER(w.RECT)]),
    ('SendMessageW', c.c_ssize_t, [w.HWND, w.UINT, w.WPARAM, w.LPARAM]),
):
    function = getattr(user, name)
    function.restype, function.argtypes = result, args
backend, original, initial_monitors = dpi_qa.discovery()
runtime._monitors = initial_monitors
state = {'phase': 0, 'started': time.monotonic(), 'due': 0., 'token': None,
         'identity': None, 'instance': 0, 'tree': '', 'node': '', 'points': [],
         'scan': 0, 'point': (0, 0), 'serial': 0, 'layout': None,
         'restoring_at': 0., 'cleaning': False, 'cleanup_at': 0., 'error': ''}


def normal_shape():
    return {(window.as_pointer(), window.blui_native_handle):
            (window.screen.as_pointer(), window.workspace.name,
             tuple((area.as_pointer(), area.type) for area in window.screen.areas))
            for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL'}


baseline_normal = normal_shape()
assert baseline_normal and hasattr(bpy.context.window, 'blui_has_desktop_interaction')


def diagnostic(label):
    controller = desktop_host._controller
    # Diagnostic RAM only: do not acquire a possibly relevant controller lock
    # or query foreign/native windows merely to print the next trace boundary.
    cached = dict(controller._state) if controller else None
    process = controller.process if controller else None
    print('DESKTOP_HOVER_BOUNDARY:', {'label': label, 'phase': state['phase'],
          'elapsed': round(time.monotonic() - state['started'], 3),
          'cleaning': state['cleaning'], 'service_phase': desktop_service._service.phase,
          'owned': list(desktop_service._service.owned), 'serial': state['serial'],
          'helper_pid': process.pid if process else None, 'cached_host': cached}, flush=True)


def screenshot(window, area, region, path):
    for index in range(_screenshot_repetitions):
        diagnostic('screenshot.' + str(index + 1) + '.before')
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert bpy.ops.screen.screenshot(filepath=path) == {'FINISHED'}
        diagnostic('screenshot.' + str(index + 1) + '.after')


def fresh():
    token = state['token']
    window = next((window for window in bpy.context.window_manager.windows
                   if (window.as_pointer(), window.blui_native_handle) == token), None)
    assert window is not None and window.blui_shell_role == 'DESKTOP', 'Owned Desktop closed unexpectedly'
    handle = int(window.blui_native_handle)
    identity = native_windows._identity(user, handle)
    assert identity and identity == state['identity'] and identity[0] == os.getpid()
    assert identity[3] == 'BLUI_DesktopWindowClass'
    assert user.GetPropW(handle, 'BLUI.DesktopHost.v1') == 1
    assert user.GetPropW(handle, 'BLUI.DesktopInstance.v1') == state['instance']
    area = max(window.screen.areas, key=lambda area: area.width * area.height)
    assert area.type == 'NODE_EDITOR' and area.spaces.active.tree_type == model.TREE
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return window, handle, area, region  # Never retain Window/Area/Tree RNA across ticks.


def event(window, kind, value, point=None):
    point = point or state['point']
    window.event_simulate(type=kind, value=value, x=point[0], y=point[1])


def originals_restored():
    diagnostic('originals.matches_shell.before')
    matches = backend.matches_shell(original)
    diagnostic('originals.matches_shell.after')
    visible = bool(user.IsWindowVisible(int(original['list']['handle'])))
    diagnostic('originals.visible.after')
    return matches and visible == original['visible']


def begin_cleanup(error=''):
    diagnostic('begin_cleanup.before')
    state.update(cleaning=True, cleanup_at=time.monotonic(), error=error)
    if state['token']:
        try:
            window, handle, _area, _region = fresh()
            if user.GetCapture() == handle:
                assert user.ReleaseCapture()
            event(window, 'ESC', 'PRESS')
            event(window, 'ESC', 'RELEASE')
        except (AssertionError, ReferenceError):
            pass
    diagnostic('cleanup.RESTORE.before')
    assert bpy.ops.wm.blui_windows_desktop(action='RESTORE') == {'FINISHED'}
    diagnostic('cleanup.RESTORE.after')
    state['serial'] = desktop_service._service.serial


def finish(code):
    diagnostic('finish.before')
    if not code:
        diagnostic('finish.status.before')
        status = desktop_service.snapshot()
        diagnostic('finish.journal.before')
        journal = Journal(session.storage_directory()).read()
        diagnostic('finish.journal.after')
        assert originals_restored() and not desktop_service._service.owned
        assert not status['enabled'] and not status['pending_restore']
        assert status['completed_serial'] >= state['serial']
        assert journal is None or (journal['shell'] is None and not journal['canvases'])
        diagnostic('finish.restore_gates.after')
    diagnostic('finish.desktop_shutdown.before')
    desktop_service.shutdown()
    diagnostic('finish.taskbar_close.before')
    taskbar.close()
    diagnostic('finish.client_close.before')
    client.close_all()
    diagnostic('finish.client_close.after')
    directory_patch.stop()
    # Both independent guardians may still write their empty final journal.
    # Never recursively remove their active OWN directory, even after verified
    # restoration. Small QA artifacts are intentionally retained for diagnosis.
    temporary._finalizer.detach()
    print('Hover restore QA artifacts retained; restoration ' +
          ('pending/failed:' if code else 'verified:'), temporary.name, flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    faulthandler.cancel_dump_traceback_later()
    os._exit(code)


def tick():
    try:
        tracing = state['phase'] >= 4 or state['cleaning']
        if tracing:
            diagnostic('runtime.tick.before')
        runtime.tick()  # Real late service tick must re-enumerate RNA after owned close.
        if tracing:
            diagnostic('runtime.tick.after')
        dpi_qa.unchanged()
        if tracing:
            diagnostic('dpi_qa.unchanged.after')
        status, now = desktop_service.snapshot(), time.monotonic()
        assert normal_shape() == baseline_normal, 'NORMAL layout/window must remain untouched'
        if state['cleaning']:
            if status['phase'] == 'IDLE' and originals_restored():
                assert not desktop_service._service.owned
                print('check_desktop_hover_restore_native: ' + ('FAIL' if state['error'] else 'PASS'),
                      state['error'] or 'real capture + Node box modal protected; idle HIGHLIGHT restore closes only owned Desktop and keeps layout/normal windows', flush=True)
                finish(1 if state['error'] else 0)
            if now - state['cleanup_at'] > 15:
                print('Hover restore cleanup pending; independent guardian journal retained', flush=True)
                finish(1)
            return .05
        if now - state['started'] > 45:
            raise TimeoutError('Desktop hover restore QA exceeded 45 seconds')
        if now < state['due']:
            return .05
        phase = state['phase']
        if phase == 0:
            assert originals_restored() and not desktop_service.snapshot()['desired']
            assert bpy.ops.wm.blui_windows_desktop(action='ENABLE') == {'FINISHED'}
            state['phase'] = 1
        elif phase == 1:
            if status['error'] and not status['desired']:
                raise RuntimeError(status['error'])
            if status['phase'] != 'CONNECTED' or desktop_service._service.adapter.busy():
                return .05
            primary = next(row['device'] for row in initial_monitors['monitors'] if row['primary'])
            state['token'] = next(token for token, device in desktop_service._service.owned.items() if device == primary)
            handle = int(state['token'][1])
            state['identity'] = native_windows._identity(user, handle)
            state['instance'] = int(user.GetPropW(handle, 'BLUI.DesktopInstance.v1') or 0)
            assert state['instance']
            window, handle, area, region = fresh()
            dpi_qa.compatible(handle, int(original['host']['handle']))
            tree = area.spaces.active.node_tree
            assert not tree.nodes, 'Only private empty fixture trees are edited'
            client_rect = w.RECT()
            assert user.GetClientRect(handle, c.byref(client_rect))
            native_point = (40, max(40, client_rect.bottom - 80))
            native_xy = (native_point[1] << 16) | native_point[0]
            user.SendMessageW(handle, 0x201, 1, native_xy)
            user.SendMessageW(handle, 0x202, 0, native_xy)
            user.SetFocus(handle)  # Exact OWN child only; no foreign/global activation.
            assert user.GetFocus() == handle, 'Real child click must activate owned Desktop input'
            node = tree.nodes.new(widgets.CALCULATOR)
            node.location, node.width = (0., 0.), 340
            tree.nodes.active = node
            state['tree'], state['node'] = tree.name, node.name
            state['point'] = (region.x + region.width // 2, region.y + region.height // 2)
            with bpy.context.temp_override(window=window, area=area, region=region):
                assert bpy.ops.node.view_all() == {'FINISHED'}
            state.update(phase=2, due=now + .5)
        elif phase == 2:
            window, handle, area, region = fresh()
            assert not user.GetCapture(), 'Do not replace an existing capture'
            if window.blui_has_desktop_interaction:
                return .05  # User held input is protected, never cancelled by QA.
            user.SetCapture(handle)
            try:
                assert user.GetCapture() == handle
                assert window.blui_has_desktop_interaction and desktop_service._service.adapter.busy()
            finally:
                if user.GetCapture() == handle:
                    assert user.ReleaseCapture()
            with bpy.context.temp_override(window=window, area=area, region=region):
                assert bpy.ops.node.select_box('INVOKE_DEFAULT', wait_for_input=True) == {'RUNNING_MODAL'}
            assert window.blui_has_desktop_interaction and window.blui_has_modal_interaction
            assert desktop_service._service.adapter.busy(), 'Real Node box selection must block lifecycle close'
            print('PASS native own capture + real Node box-selection modal remain guarded', flush=True)
            event(window, 'ESC', 'PRESS')
            event(window, 'ESC', 'RELEASE')
            state.update(phase=3, due=now + .3)
        elif phase == 3:
            window, handle, area, region = fresh()
            if window.blui_has_desktop_interaction:
                return .05
            if not state.get('view_ready'):
                # The first view_all ran before the new Node had drawn bounds.
                with bpy.context.temp_override(window=window, area=area, region=region):
                    assert bpy.ops.node.view_all() == {'FINISHED'}
                state.update(view_ready=True, due=now + .5)
                return .05
            node = bpy.data.node_groups[state['tree']].nodes[state['node']]
            width, height = node.dimensions
            assert width > 10 and height > 10, 'Actual native Node draw dimensions required'
            scale = width / node.width
            points = []
            # First target is the bottom-left calculator key's interior. The
            # rendered dimensions are view-space, including UI_SCALE_FAC.
            x, y = region.view2d.view_to_region(width * .125, -height + 22 * scale, clip=False)
            if 3 < x < region.width - 3 and 3 < y < region.height - 3:
                points.append((region.x + x, region.y + y))
            for fraction in (.125, .375, .625, .875):
                for row in range(30, int(height / scale) - 4, 12):
                    x, y = region.view2d.view_to_region(width * fraction, -row * scale, clip=False)
                    if 3 < x < region.width - 3 and 3 < y < region.height - 3:
                        points.append((region.x + x, region.y + y))
            assert points, 'Rendered calculator must have interior hover targets'
            print('DESKTOP_HOVER_TARGETS:', {'handle': handle, 'focus': int(user.GetFocus() or 0),
                  'region': (region.x, region.y, region.width, region.height),
                  'node_location': tuple(node.location), 'dimensions': (width, height),
                  'scale': scale, 'first_point': points[0], 'points': len(points),
                  'old_gate': window.blui_has_modal_interaction,
                  'lifecycle_gate': window.blui_has_desktop_interaction}, flush=True)
            screenshot(window, area, region, 'D:/BlenderUI/build/desktop-hover-targets.png')
            state.update(phase=4, points=points, scan=0)
        elif phase == 4:
            window, _handle, area, region = fresh()
            if state['scan'] and not window.blui_has_desktop_interaction:
                assert not desktop_service._service.adapter.busy()
                # HIGHLIGHT is not a modal state in button_modal_state(); old
                # strict guard need not be True for ordinary actual hover.
                # Native source guards separately prove it is unchanged.
                tree = bpy.data.node_groups[state['tree']]
                state['layout'] = deepcopy(serialization.snapshot(tree))
                screenshot(window, area, region, 'D:/BlenderUI/build/desktop-hover-restore.png')
                print('PASS actual Calculator pointer hover:', {'point': state['point'],
                      'focus': int(user.GetFocus() or 0), 'old_gate': window.blui_has_modal_interaction,
                      'lifecycle_gate': window.blui_has_desktop_interaction}, flush=True)
                diagnostic('actual.RESTORE.before')
                assert bpy.ops.wm.blui_windows_desktop(action='RESTORE') == {'FINISHED'}
                diagnostic('actual.RESTORE.after')
                state.update(phase=5, serial=desktop_service._service.serial, restoring_at=now)
                diagnostic('actual.RESTORE.timer_return')
                return .05
            if state['scan'] >= len(state['points']):
                raise AssertionError('Actual calculator button HIGHLIGHT was never observed')
            state['point'] = state['points'][state['scan']]
            state['scan'] += 1
            event(window, 'MOUSEMOVE', 'NOTHING')  # Not OS-global cursor/input.
            state['due'] = now + .15  # Let native UI process/draw the real hover event.
        else:
            if now - state['restoring_at'] > 8:
                raise AssertionError('Unpressed hover starved ack-gated Desktop close')
            if status['phase'] != 'IDLE':
                return .05
            assert status['completed_serial'] >= state['serial']
            assert not status['enabled'] and not status['pending_restore'] and originals_restored()
            assert not desktop_service._service.owned
            tokens = {(window.as_pointer(), window.blui_native_handle) for window in bpy.context.window_manager.windows}
            assert state['token'] not in tokens
            assert serialization.snapshot(bpy.data.node_groups[state['tree']]) == state['layout']
            print('PASS actual RESTORE acknowledgement closes owned Desktop despite prior hover; NORMAL/layout intact', flush=True)
            begin_cleanup()
        return .05
    except Exception:
        traceback.print_exc()
        if state['cleaning']:
            finish(1)
        try:
            begin_cleanup('See hover restore native traceback')
        except Exception:
            traceback.print_exc()
            finish(1)
        return .05


bpy.app.timers.register(tick, first_interval=.5)
