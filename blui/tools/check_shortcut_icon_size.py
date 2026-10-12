# SPDX-License-Identifier: GPL-2.0-or-later
"""A 16px-only shortcut icon must not shrink inside a padded 256px system icon."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import bpy
from bl_ui import space_filebrowser_shell

root = Path(tempfile.mkdtemp(prefix='blui_icon_size_'))
files = root / 'files'
files.mkdir()
(files / 'target.txt').write_text('fixture', encoding='utf-8')
pixels = b'\x00\xff\x00\xff' * (16 * 16)
bitmap = struct.pack('<IiiHHIIiiII', 40, 16, 32, 1, 32, 0, len(pixels), 0, 0, 0, 0) + pixels + bytes(64)
(root / 'small.ico').write_bytes(struct.pack('<HHH', 0, 1, 1) +
    struct.pack('<BBBBHHII', 16, 16, 0, 0, 1, 32, len(bitmap), 22) + bitmap)
subprocess.run(['pwsh', '-NoProfile', '-Command', '''
$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $env:BLUI_ICON_FIXTURE 'files/Small.lnk'))
$link.TargetPath = Join-Path $env:BLUI_ICON_FIXTURE 'files/target.txt'
$link.IconLocation = (Join-Path $env:BLUI_ICON_FIXTURE 'small.ico') + ',0'
$link.Save()
'''], env=dict(os.environ, BLUI_ICON_FIXTURE=str(root)), check=True, creationflags=subprocess.CREATE_NO_WINDOW)
state = {'step': 0, 'started': time.monotonic()}


def override():
    return bpy.context.temp_override(window=state['window'], area=state['area'], region=state['region'])


def step():
    if time.monotonic() - state['started'] > 25:
        raise TimeoutError('Shortcut icon regression timed out')
    n = state['step']
    if n == 0:
        space_filebrowser_shell.unregister()
        window = bpy.context.window_manager.windows[0]
        area = next(area for area in window.screen.areas if area.type == 'FILE_BROWSER')
        state.update(window=window, area=area, region=next(r for r in area.regions if r.type == 'WINDOW'))
        with override():
            area.spaces.active.params.display_type = 'THUMBNAIL'
            bpy.ops.file.select_bookmark(dir=str(files))
        delay = 1.0
    elif n == 1:
        with override():
            bpy.ops.file.select_all(action='SELECT')
            entry = next(entry for entry in bpy.context.selected_files if entry.relative_path == 'Small.lnk')
            if not entry.preview_icon_id:
                return .1
            assert not entry.is_directory
            bpy.ops.file.select_all(action='DESELECT')
        delay = .3
    elif n == 2:
        with override():
            bpy.ops.screen.screenshot(filepath=str(root / 'icons.png'))
        delay = .2
    else:
        screenshot = bpy.data.images.load(str(root / 'icons.png'))
        width, height = screenshot.size[:]
        pixels = list(screenshot.pixels)
        region = state['region']
        green = 0
        for y in range(max(0, region.y), min(height, region.y + region.height)):
            for x in range(max(0, region.x), min(width, region.x + region.width)):
                index = (y * width + x) * 4
                green += pixels[index + 1] > .8 and pixels[index] < .1 and pixels[index + 2] < .1
        assert green > 4000, 'Low-resolution shortcut remained too small: %d green pixels' % green
        print('PASS 16px-only shortcut fills its thumbnail instead of a tiny jumbo corner: %d pixels' % green, flush=True)
        print('check_shortcut_icon_size: PASS', root, flush=True)
        os._exit(0)
    state['step'] += 1
    return delay


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)


bpy.app.timers.register(guarded, first_interval=.5)
