# SPDX-License-Identifier: GPL-2.0-or-later
"""PRIMARY AGENT ONLY: serial disposable native system-bar handoff/recovery QA.

Run --factory-startup --enable-event-simulate with an isolated CONFIG. This test
temporarily hides the real Explorer bars through its own independent guard;
it never moves/resizes foreign windows, kills Explorer, edits registry or SPI.
Only its own QA-created helper is terminated in the crash-recovery phase.
Keep the temporary recovery journals on any unresolved cleanup failure.
"""
import os
import sys
import tempfile
import time
import traceback
import bpy
from blui_desktop import monitors, runtime, session, taskbar, taskbar_appbar
from blui_desktop import taskbar_native, window_placement

session.disable_for_tests = True
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
temporary = tempfile.TemporaryDirectory(prefix='blui_reservation_native_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
started = time.monotonic()
backend = taskbar_native.WindowsBars()  # Read-only calls in this fixture.
primary = backend.primary()
assert primary is not None, 'No verified Explorer primary taskbar'
original_state = backend.reservation_state(dict(primary, visible=True))
assert original_state is not None, 'Cannot read original Explorer state'
original_bars = backend.enumerate()
initial = monitors.snapshot()
baseline = {row['device']: row['work'][:] for row in initial['monitors']}
display = next(row for row in initial['monitors'] if row['primary'])
device = display['device']
source = next(window for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL')
source_key = (source.as_pointer(), source.blui_native_handle)
appbar = taskbar_appbar.AppBarController()
controller = taskbar.Controller(temporary.name)
state = {'phase': 0, 'bar': None, 'free_work': None, 'rect': None, 'error': '',
         'cleaning': False, 'deadline': 0., 'crash_helper': None, 'pass': False}


def fresh(key, role):
    window = next((window for window in bpy.context.window_manager.windows
                   if (window.as_pointer(), window.blui_native_handle) == key), None)
    assert window is not None and window.blui_shell_role == role, 'Owned QA role/window changed'
    user = window_placement._api()
    identity = window_placement._own(user, int(window.blui_native_handle))
    assert identity[0] == os.getpid(), 'Fixture never writes another process window'
    return window


def current():
    snapshot = monitors.snapshot()
    assert {row['device'] for row in snapshot['monitors']} == set(baseline), 'Topology changed during QA'
    row = next(row for row in snapshot['monitors'] if row['device'] == device)
    assert row['rect'] == display['rect'], 'Primary monitor geometry changed during QA'
    return snapshot, row


def restored():
    primary = backend.primary()
    if primary is None:
        return False
    if backend.reservation_state(dict(primary, visible=True)) != original_state:
        return False
    for row in original_bars:
        if row['visible'] and backend.matches(row) and not backend.visible(row):
            return False
    snapshot, _display = current()
    return all(row['work'] == baseline[row['device']] for row in snapshot['monitors'])


def close_owned_bar():
    appbar.close()  # Unregister before HWND destruction.
    if state['bar'] is not None:
        window = fresh(state['bar'], 'TASKBAR')
        with bpy.context.temp_override(window=window):
            assert bpy.ops.wm.window_close(force_close=True) == {'FINISHED'}
        state['bar'] = None


def begin_cleanup(error=''):
    if error:
        state['error'] = error
    try:
        close_owned_bar()
    finally:
        # Nonblocking EOF/shutdown; both guardians retain durable undo intent.
        controller.close()
        state['cleaning'], state['deadline'] = True, time.monotonic() + 8


def finish(success):
    if success:
        temporary.cleanup()
    else:
        # The guardian may still need these files. Detach only this temp cleanup,
        # never erase recovery intent merely because the assertion failed.
        temporary._finalizer.detach()
        print('RECOVERY_JOURNALS:', temporary.name, flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if success else 1)


def tick():
    global controller
    try:
        if state['cleaning']:
            if restored():
                print('PASS original taskbar visibility/state and all monitor work areas restored', flush=True)
                finish(state['pass'] and not state['error'])
            if time.monotonic() > state['deadline']:
                print('FAIL recovery remains pending:', state['error'], flush=True)
                finish(False)
            return .1
        if time.monotonic() - started > 90:
            raise TimeoutError('Native reservation QA exceeded 90 seconds')
        result = controller.tick()
        diagnostic = (state['phase'], result.get('state'), result.get('error'),
                      result.get('hidden_count'), result.get('reservation_pending'),
                      backend.reservation_state(dict(backend.primary(), visible=True)),
                      tuple(row['work'][3] for row in monitors.snapshot()['monitors']))
        if diagnostic != state.get('diagnostic'):
            state['diagnostic'] = diagnostic
            print('QA phase/state/hidden/pending/physical/work:', diagnostic,
                  'elapsed', round(time.monotonic() - started, 2),
                  'baseline', baseline, 'original', original_state, flush=True)
        # The deliberate helper crash legitimately reports pending recovery;
        # phase 5 verifies the second guardian against actual Windows instead.
        if result['error'] and state['phase'] != 5:
            raise RuntimeError(result['error'])
        phase = state['phase']
        if phase == 0:
            if not result['events_available']:
                return .1
            controller.request('hide')
            state['phase'] = 1
        elif phase == 1:
            if not result.get('reservation_reclaimed') or not result['hidden_count']:
                return .1
            snapshot, row = current()
            if not original_state & 1 and row['work'][3] <= baseline[device][3]:
                return .1  # Wait for the Shell's asynchronous reservation notification.
            state['free_work'] = row['work'][:]
            assert backend.reservation_state(dict(backend.primary(), visible=True)) & 1
            print('PASS isolated guard releases Explorer reservation before visibility hide', row['work'], flush=True)
            before = {window.as_pointer() for window in bpy.context.window_manager.windows}
            source = fresh(source_key, 'NORMAL')
            with bpy.context.temp_override(window=source):
                assert bpy.ops.wm.blui_shell_window_create(role='TASKBAR',
                    width=row['rect'][2] - row['rect'][0], height=56) == {'FINISHED'}
            added = [window for window in bpy.context.window_manager.windows if window.as_pointer() not in before]
            assert len(added) == 1 and added[0].blui_shell_role == 'TASKBAR'
            state['bar'] = (added[0].as_pointer(), added[0].blui_native_handle)
            bar = fresh(state['bar'], 'TASKBAR')
            state['rect'] = appbar.reconcile({device: bar}, snapshot, 56)[device]
            # Honours other AppBars. There must be no *additional* original blank strip.
            assert abs(state['rect'][3] - state['free_work'][3]) <= 2, (state['rect'], state['free_work'])
            window_placement.place(bar.blui_native_handle, state['rect'], snapshot, preferred=device)
            state['phase'] = 2
        elif phase == 2:
            snapshot, row = current()
            if row['work'][3] != state['rect'][1]:
                return .1
            bar = fresh(state['bar'], 'TASKBAR')
            rect = appbar.reconcile({device: bar}, snapshot, 56)[device]
            assert rect == state['rect'], 'Own work-area change must not reserve height twice'
            print('PASS own AppBar occupies reclaimed edge once, without original blank strip', rect, flush=True)
            close_owned_bar()
            controller.request('restore')
            state['phase'] = 3
        elif phase == 3:
            if result.get('reservation_pending') or not restored():
                return .1
            print('PASS explicit normal restore returns original state/work areas', flush=True)
            # Reuse the exact client; its primary helper and second guardian are
            # both fixture-created, not any pre-existing user process.
            controller.request('hide')
            state['phase'] = 4
        elif phase == 4:
            if not result.get('reservation_reclaimed') or not result['hidden_count']:
                return .1
            process = controller.process
            assert process is not None and process.pid != os.getpid() and process.poll() is None
            assert controller.directory == temporary.name, 'Only this fixture-created helper may be terminated'
            state['crash_helper'] = process.pid
            process.terminate()  # Deliberate owned-helper crash, NEVER Explorer/user BLUI.
            state['phase'] = 5
        elif phase == 5:
            if not restored():
                return .1
            print('PASS independent second guardian restores after owned helper crash', state['crash_helper'], flush=True)
            state['pass'] = True
            print('check_taskbar_reservation_native: PASS', flush=True)
            begin_cleanup()
        return .1
    except Exception as exc:
        traceback.print_exc()
        try:
            begin_cleanup(str(exc))
        except Exception:
            traceback.print_exc()
            finish(False)
        return .1


bpy.app.timers.register(tick, first_interval=.4)
