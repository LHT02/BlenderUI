# SPDX-License-Identifier: GPL-2.0-or-later
"""Serial native settings/DPI QA; PRIMARY AGENT RUNS ONLY in an isolated CONFIG.

--factory-startup --enable-event-simulate --python-exit-code 1 --python this file
No real AppBar registration, notification host, system-bar control or foreign
task enumeration. Only one verified current-process task is shown. A real icon
Job extracts this BLUI executable; only the application launcher is intercepted.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest import mock
import bpy
from blui_desktop import client, icon_cache, monitors, native_windows, notification_client
from blui_desktop import runtime, session, taskbar_actions, taskbar_options_ui, taskbar_settings, taskbar_windows

session.disable_for_tests = True
temporary = tempfile.TemporaryDirectory(prefix='blui_bar_appearance_qa_')
os.environ['BLUI_DESKTOP_CONFIG'] = temporary.name
if bpy.app.timers.is_registered(runtime.tick):
    bpy.app.timers.unregister(runtime.tick)
notification_client.close()
taskbar_settings.shutdown()
started = time.monotonic()
snapshot = monitors.snapshot()
assert snapshot['monitors'], 'Native appearance QA requires a connected monitor'
display = next((row for row in snapshot['monitors'] if row['primary']), snapshot['monitors'][0])
runtime._monitors = snapshot
source = next(window for window in bpy.context.window_manager.windows if window.blui_shell_role == 'NORMAL')
source_key = (source.as_pointer(), source.blui_native_handle)
user = native_windows._api()
handle = int(source.blui_native_handle)
identity = native_windows._identity(user, handle)
assert identity and identity[0] == os.getpid(), 'Only an owned normal window can be the fake task'
metadata = native_windows._metadata(os.getpid())
executable = metadata['executable']
assert executable and not metadata['app_id'], 'Fixture must use its actual unpackaged BLUI executable'
runtime._tasks = [{'handle': str(handle), 'pid': identity[0], 'thread_id': identity[1],
                   'process_started': identity[2], 'window_class': identity[3],
                   'title': 'Owned appearance QA', 'actionable': True, 'active': False,
                   'minimized': False, 'monitor': display['device'], **metadata}]
runtime._last_tasks = time.monotonic() + 3600
taskbar_windows.set_alignment('CENTER')
icon_job = client.Job('icons', [executable], timeout=6)
launches = []
launcher = mock.patch.object(taskbar_actions, 'launch_group', side_effect=lambda group: launches.append(group['key']))
launcher.start()
cases = [(height, icon, scale) for scale in (1, 2) for height, icon in ((32, 16), (80, 64), (160, 64))]
state = {'phase': 0, 'due': 0., 'case': 0, 'bar': None, 'bounds': None, 'start_point': None}


def live_bar():
    window = next((window for window in taskbar_windows.role_windows('TASKBAR')
                   if (window.as_pointer(), window.blui_native_handle) == state['bar']), None)
    assert window is not None, 'Appearance fixture bar disappeared'
    value = native_windows._identity(user, int(window.blui_native_handle))
    assert value and value[0] == os.getpid(), 'Fixture bar must belong to this PID'
    return window


def hover(window, point):
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=point[0], y=point[1])


def hovered_operator(window):
    area = window.screen.areas[0]
    region = next(region for region in area.regions if region.type == 'WINDOW')
    with bpy.context.temp_override(window=window, area=area, region=region):
        value = getattr(bpy.context, 'blui_shell_hover_button', None)
        return (value.bl_rna.identifier, getattr(value, 'key', '')) if value else ('', '')


def capture_glyph(window, case):
    """Case-specific physical glyph proof; leave qa_shell_pixels' 32px default intact."""
    height_logical, icon_logical, scale = case
    path = Path('D:/BlenderUI/build') / f'shell-bar-h{height_logical}-i{icon_logical}-s{scale}.png'
    area = window.screen.areas[0]
    with bpy.context.temp_override(window=window, area=area):
        assert bpy.ops.screen.screenshot(filepath=str(path)) == {'FINISHED'}
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = image.size
        expected_height = round(height_logical * scale * display['dpi'][1] / 96)
        assert height == expected_height, ('Native bar height/DPI mismatch', case, height, expected_height)
        assert width == display['work'][2] - display['work'][0]
        pixels = list(image.pixels)
        colored = []
        for y in range(height):
            for x in range(width // 4, 3 * width // 4):
                offset = 4 * (y * width + x)
                rgb = pixels[offset:offset + 3]
                if max(rgb) > .35 and max(rgb) - min(rgb) > .18:
                    colored.append((x, y))
        assert colored, ('Actual cached executable glyph is blank', case)
        bounds = (min(x for x, y in colored), min(y for x, y in colored),
                  max(x for x, y in colored), max(y for x, y in colored))
        physical_icon = icon_logical * bpy.context.preferences.system.ui_scale
        actual_width, actual_height = bounds[2] - bounds[0] + 1, bounds[3] - bounds[1] + 1
        assert .55 * physical_icon <= actual_width <= 1.2 * physical_icon + 4, (
            'Actual glyph width did not follow icon size/UI scale', case, bounds, physical_icon)
        assert .45 * physical_icon <= actual_height <= 1.2 * physical_icon + 4, (
            'Actual glyph height did not follow icon size/UI scale', case, bounds, physical_icon)
        margin = max(1, round(bpy.context.preferences.system.ui_scale))
        assert bounds[1] >= margin and bounds[3] < height - margin, ('Clipped glyph', case, bounds, height)
        print('APPEARANCE_PIXELS', case, 'WINDOW', width, height, 'GLYPH', bounds,
              'UI_SCALE', bpy.context.preferences.system.ui_scale, str(path), flush=True)
        return bounds
    finally:
        bpy.data.images.remove(image)


def finish(code):
    try:
        icon_job.close()
        launcher.stop()
        taskbar_windows.close()
        notification_client.close()
        taskbar_settings.shutdown()
        client.close_all()
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        temporary.cleanup()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)


def tick():
    try:
        if time.monotonic() - started > 45:
            raise TimeoutError('Native taskbar appearance QA exceeded 45 seconds')
        if time.monotonic() < state['due']:
            return .05
        phase = state['phase']
        if phase == 0:
            if not icon_job.done():
                return .05
            icon_cache.apply(icon_job.result())
            assert icon_cache.value(executable), 'Native executable icon extraction failed'
            # Clear only this disposable normal window's initial UI highlight.
            source.event_simulate(type='ESC', value='PRESS')
            source.event_simulate(type='ESC', value='RELEASE')
            source.event_simulate(type='MOUSEMOVE', value='NOTHING', x=source.width // 2, y=source.height // 2)
            state['phase'], state['due'] = 1, time.monotonic() + .2
        elif phase == 1:
            case = cases[state['case']]
            height, icon, scale = case
            bpy.context.preferences.view.ui_scale = scale
            options = bpy.context.window_manager.blui_taskbar_options
            options.icon_size, options.height = icon, height
            assert taskbar_options_ui.values() == {'height': height, 'icon_size': icon}
            assert (options.height, options.icon_size) == (height, icon), 'RNA mirror diverged from canonical settings'
            if state['bar'] is None:
                bars = taskbar_windows.open_for_displays(bpy.context, snapshot, all_displays=False)
                assert len(bars) == 1
                state['bar'] = (bars[0].as_pointer(), bars[0].blui_native_handle)
            else:
                assert not runtime.interaction_busy(None), 'Fixture must release held UI before geometry updates'
                taskbar_windows.tick(snapshot)
            bar = live_bar()
            assert len(taskbar_actions.current_groups(bar)) == 1
            assert taskbar_actions.current_groups(bar)[0]['tasks'][0]['pid'] == os.getpid()
            state['phase'], state['due'] = 2, time.monotonic() + .35
        elif phase == 2:
            bar = live_bar()
            state['bounds'] = capture_glyph(bar, cases[state['case']])
            _height, icon, _scale = cases[state['case']]
            unit_scale = bpy.context.preferences.system.ui_scale
            point = (round(((icon + 8) / 2 + 8) * unit_scale), bar.height // 2)
            assert point[0] < bar.width // 8, 'Start must remain in the left strip'
            state['start_point'] = point
            hover(bar, point)
            state['phase'], state['due'] = 3, time.monotonic() + .12
        elif phase == 3:
            bar = live_bar()
            operator, _key = hovered_operator(bar)
            assert operator == 'WM_OT_blui_start_menu', ('Start is not left-anchored', cases[state['case']], state['start_point'], operator)
            bounds = state['bounds']
            point = ((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
            assert bar.width // 4 <= point[0] <= 3 * bar.width // 4
            assert point[0] > state['start_point'][0] + round(80 * bpy.context.preferences.system.ui_scale)
            hover(bar, point)
            state['phase'], state['due'] = 4, time.monotonic() + .12
        elif phase == 4:
            bar = live_bar()
            operator, key = hovered_operator(bar)
            assert operator == 'WM_OT_blui_taskbar_group' and key == taskbar_actions.current_groups(bar)[0]['key']
            assert not launches, 'No appearance test may launch an application'
            print('PASS SETTINGS_DPI_START_LEFT_APP_CENTER', cases[state['case']], flush=True)
            hover(bar, (bar.width // 5, bar.height // 2))
            state['case'] += 1
            if state['case'] == len(cases):
                print('check_taskbar_appearance_ui: PASS (6 native RNA/UI-scale cases, actual glyph size, separate left Start, centered app, no AppBar/system/foreign actions)', flush=True)
                finish(0)
            state['phase'], state['due'] = 1, time.monotonic() + .15
        return .05
    except Exception:
        traceback.print_exc()
        finish(1)


bpy.app.timers.register(tick, first_interval=.3)
