# SPDX-License-Identifier: GPL-2.0-or-later
"""Windowed Explorer integration tests. -- --interactive leaves a QA window open."""
import json
import os
from pathlib import Path
import sys
import subprocess
import struct
import tempfile
import time

import bpy
from bl_operators import blui_file
from blui_explorer import shell_client

ROOT = Path(tempfile.mkdtemp(prefix="blui_explorer_qa_"))
(ROOT / "Destination").mkdir()
(ROOT / "Folder").mkdir()
(ROOT / "sample.txt").write_text("BLUI fixture\n", encoding="utf-8")
(ROOT / "second.txt").write_text("second fixture\n", encoding="utf-8")
(ROOT / "Folder" / "inside.txt").write_text("inside\n", encoding="utf-8")
# Deliberately asymmetric icon: red top, blue bottom catches vertical inversion.
icon_pixels = b''.join((b'\xff\x00\x00\xff' if y < 16 else b'\x00\x00\xff\xff') * 32 for y in range(32))
icon_bitmap = struct.pack('<IiiHHIIiiII', 40, 32, 64, 1, 32, 0, 4096, 0, 0, 0, 0) + icon_pixels + bytes(128)
(ROOT / 'orientation.ico').write_bytes(struct.pack('<HHH', 0, 1, 1) +
    struct.pack('<BBBBHHII', 32, 32, 0, 0, 1, 32, len(icon_bitmap), 22) + icon_bitmap)
subprocess.run(['pwsh', '-NoProfile', '-Command', r'''
$wsh = New-Object -ComObject WScript.Shell
$link = $wsh.CreateShortcut((Join-Path $env:BLUI_FIXTURE 'Folder shortcut.lnk'))
$link.TargetPath = Join-Path $env:BLUI_FIXTURE 'Folder'
$link.IconLocation = (Join-Path $env:BLUI_FIXTURE 'orientation.ico') + ',0'
$link.Save()
$link = $wsh.CreateShortcut((Join-Path $env:BLUI_FIXTURE 'Broken shortcut.lnk'))
$link.TargetPath = Join-Path $env:BLUI_FIXTURE 'missing.txt'
$link.Save()
'''], env=dict(os.environ, BLUI_FIXTURE=str(ROOT)), check=True,
               creationflags=subprocess.CREATE_NO_WINDOW)
PASTE = Path(tempfile.mkdtemp(prefix="blui_paste_qa_", dir=Path(__file__).resolve().parents[3] / 'build'))
MOVED = Path(tempfile.mkdtemp(prefix="blui_move_qa_"))
interactive = "--interactive" in sys.argv
state = {"step": 0, "started": time.monotonic(), "failures": []}
print("EXPLORER_QA_ROOT", ROOT, flush=True)


def report(ok, message):
    print(("PASS " if ok else "FAIL ") + message, flush=True)
    if not ok:
        state["failures"].append(message)


def override(**extra):
    return bpy.context.temp_override(window=state["window"], area=state["area"],
                                     region=state["region"], **extra)


def quit_test():
    shell_client.close_all()
    print("check_explorer:", "PASS" if not state["failures"] else "FAIL", flush=True)
    sys.stdout.flush()
    os._exit(bool(state["failures"]))


def step():
    if time.monotonic() - state["started"] > 50:
        report(False, "integration test timed out")
        quit_test()
    current = state["step"]
    if current == 0:
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == 'FILE_BROWSER')
        state.update(window=window, area=area, region=next(r for r in area.regions if r.type == 'WINDOW'))
        with override():
            bpy.ops.file.select_bookmark(dir=str(ROOT))
            area.spaces.active.params.display_type = 'THUMBNAIL'
        state["step"] += 1
        return 1.0
    if current == 1:
        with override():
            bpy.ops.file.select_all(action='SELECT')
            paths = blui_file.selected_paths(bpy.context)
            report(set(Path(p).name for p in paths) == {'sample.txt', 'second.txt', 'Folder', 'Destination',
                                                     'Folder shortcut.lnk', 'Broken shortcut.lnk', 'orientation.ico'},
                   "Select All includes files and folders, excludes parent")
            report(sum(p.endswith('.lnk') for p in paths) == 2,
                   "Folder and broken shortcuts retain real .lnk filenames")
            bpy.ops.file.explorer_copy_path()
            report(set(bpy.context.window_manager.clipboard.splitlines()) == set(paths), "Copy Path uses selected paths")
            entries = list(bpy.context.selected_files)
            state["sample_entry"] = next(f for f in entries if f.relative_path == 'sample.txt')
        state["step"] += 1
        return 0.2
    if current == 2:
        with override(selected_files=[state["sample_entry"]]):
            report(bpy.ops.file.explorer_rename(name='renamed.txt', source=str(ROOT / 'sample.txt')) == {'FINISHED'},
                   "Rename operator succeeds")
            report((ROOT / 'renamed.txt').is_file() and not (ROOT / 'sample.txt').exists(), "Rename changes the real file")
        with override():
            bpy.ops.file.explorer_new_file(name='new.txt')
            report((ROOT / 'new.txt').is_file(), "New Text File exists on disk")
            bpy.ops.file.filepath_drop(filepath=str(ROOT / 'renamed.txt'), directory=str(ROOT / 'Destination'), move=True)
        state["step"] += 1
        return 0.2
    if current == 3:
        if blui_file._jobs:
            return 0.2
        report((ROOT / 'Destination/renamed.txt').is_file() and not (ROOT / 'renamed.txt').exists(),
               "C drop operator forwards move to the actual destination folder")
        with override():
            bpy.ops.file.filepath_drop(filepath=str(ROOT / 'second.txt'), directory=str(ROOT / 'Destination'), move=False)
        state["step"] += 1
        return 0.2
    if current == 4:
        if blui_file._jobs:
            return 0.2
        report((ROOT / 'Destination/second.txt').read_bytes() == (ROOT / 'second.txt').read_bytes(),
               "Copy drop keeps source and copies bytes")
        with override():
            bpy.ops.file.select_all(action='SELECT')
            bpy.ops.file.clipboard_copy()
            bpy.ops.file.select_bookmark(dir=str(PASTE))
        state['step'] += 1
        return 0.8
    if current == 5:
        with override():
            started = time.monotonic()
            bpy.ops.file.clipboard_paste()
            report(time.monotonic() - started < 0.25, "Paste returns without blocking UI")
        state['step'] += 1
        return 0.3
    if current == 6:
        if blui_file._jobs or bpy.app.timers.is_registered(blui_file._refresh_now):
            return 0.5
        report((PASTE / 'Folder/inside.txt').read_bytes() == (ROOT / 'Folder/inside.txt').read_bytes(),
               "System clipboard copies folder contents across volumes")
        report((PASTE / 'Folder shortcut.lnk').read_bytes() == (ROOT / 'Folder shortcut.lnk').read_bytes(),
               "Clipboard copies shortcut itself, not its target")
        with override():
            bpy.ops.file.select_all(action='SELECT')
            if not blui_file.selected_paths(bpy.context):
                return 0.3  # The asynchronous directory reader may still be rebuilding.
            bpy.ops.file.clipboard_cut()
            bpy.ops.file.select_bookmark(dir=str(MOVED))
        state['step'] += 1
        return 0.8
    if current == 7:
        with override():
            bpy.ops.file.clipboard_paste()
        state['step'] += 1
        return 0.3
    if current == 8:
        if blui_file._jobs:
            return 0.2
        report(not list(PASTE.iterdir()) and (MOVED / 'Folder/inside.txt').is_file(),
               "Cut-paste moves the full tree across volumes")
        report((ROOT / 'Folder/inside.txt').is_file() and (MOVED / 'Folder shortcut.lnk').is_file(),
               "Moving a shortcut preserves its target")
        with override():
            bpy.ops.file.select_bookmark(dir=str(ROOT))
        state['step'] += 1
        return 0.8
    if current == 9:
        # Dismiss the completion popup, then draw the real menu (not a mock layout).
        state["window"].event_simulate(type='ESC', value='PRESS')
        state["window"].event_simulate(type='ESC', value='RELEASE')
        with override():
            bpy.ops.file.select_all(action='DESELECT')
            bpy.ops.wm.call_menu(name='FILEBROWSER_MT_context_menu')
        state["step"] += 1
        return 1.0
    if current == 10:
        state["window"].event_simulate(type='ESC', value='PRESS')
        state["window"].event_simulate(type='ESC', value='RELEASE')
        with override():
            bpy.ops.file.select_all(action='SELECT')
            bpy.ops.wm.call_menu(name='FILEBROWSER_MT_context_menu')
        state["step"] += 1
        return 1.0
    if interactive:
        print("EXPLORER_QA_READY", ROOT, flush=True)
        with override():
            bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[3] / 'build/explorer-menu.png'))
        return None
    quit_test()


def guarded():
    try:
        return step()
    except Exception:
        import traceback
        traceback.print_exc()
        report(False, "unhandled exception")
        quit_test()


bpy.app.timers.register(guarded, first_interval=1.0)
