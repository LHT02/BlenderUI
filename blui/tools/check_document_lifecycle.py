# SPDX-License-Identifier: GPL-2.0-or-later
"""Disposable documents: image isolation/cache release, close cancellation, save and removal."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import bpy
from bl_operators import blui_documents as documents
from bl_ui import space_filebrowser_shell

root = Path(tempfile.mkdtemp(prefix='blui_document_qa_'))
for name, pixel in (('a.bmp', b'\x00\x00\xff'), ('b.bmp', b'\xff\x00\x00')):
    payload = pixel * (32 * 32)
    (root / name).write_bytes(b'BM' + struct.pack('<IHHI', len(payload) + 54, 0, 0, 54) +
        struct.pack('<IiiHHIIiiII', 40, 32, 32, 1, 24, 0, len(payload), 0, 0, 0, 0) + payload)
(root / 'text.txt').write_text('saved\n', encoding='utf-8')
state = {'step': 0, 'started': time.monotonic()}


def context(window, area=None):
    area = area or next(iter(window.screen.areas))
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    return bpy.context.temp_override(window=window, area=area, region=region)


def open_window(kind):
    editor = 'IMAGE_EDITOR' if kind == 'Image' else 'TEXT_EDITOR'
    workspace = next(w for w in bpy.data.workspaces if any(a.type == editor for s in w.screens for a in s.areas))
    before = {w.as_pointer() for w in bpy.context.window_manager.windows}
    with context(state['source']):
        bpy.ops.wm.window_new(workspace=workspace.name)
    return next(w for w in bpy.context.window_manager.windows if w.as_pointer() not in before)


def decision(action, choice):
    matches = [(token, request) for token, request in documents._requests.items() if request.action == action]
    assert matches, 'Document action did not prompt: ' + action
    token, request = matches[-1]
    # Dismiss the visual popup first; the decision operator uses the same token.
    for value in ('PRESS', 'RELEASE'):
        request.window.event_simulate(type='ESC', value=value)
    with context(request.window):
        assert bpy.ops.wm.blui_document_decision(token=token, choice=choice) == {'FINISHED'}


def step():
    n = state['step']
    if time.monotonic() - state['started'] > 45:
        raise TimeoutError('Document regression timed out')
    if n == 0:
        space_filebrowser_shell.unregister()
        state['source'] = bpy.context.window_manager.windows[0]
        state['a'] = open_window('Image')
        delay = 0.5
    elif n == 1:
        with context(state['a']):
            assert bpy.context.area.type == 'IMAGE_EDITOR'
            assert 'UV' not in bpy.context.space_data.bl_rna.properties['mode'].enum_items
            bpy.ops.image.open(filepath=str(root / 'a.bmp'))
            state['first_name'] = bpy.context.space_data.image.name
        state['b'] = open_window('Image')
        delay = 0.5
    elif n == 2:
        with context(state['b']):
            bpy.ops.image.open(filepath=str(root / 'a.bmp'))
            state['other'] = bpy.context.space_data.image
        with context(state['a']):
            assert bpy.context.space_data.image != state['other'], 'Images shared between independent windows'
            current = bpy.context.space_data.image
            try:
                bpy.ops.image.open(filepath=str(root / '0-missing.bmp'))
            except RuntimeError:
                pass  # Native error reports become Python exceptions.
            assert bpy.context.space_data.image == current, 'Failed load discarded the current image'
            try:
                bpy.ops.image.open(directory=str(root) + os.sep,
                                   files=[{'name': '0-missing.bmp'}, {'name': 'b.bmp'}])
            except RuntimeError:
                pass
            assert bpy.context.space_data.image.filepath.endswith('b.bmp'), 'A failed path broke later loading'
            assert state['first_name'] not in bpy.data.images, 'Old temporary image was retained'
            state['a_image_name'] = bpy.context.space_data.image.name
            assert bpy.context.space_data.image.source == 'FILE'
        assert state['other'].filepath.endswith('a.bmp')
        print('PASS Failed image load retains current image; later valid selection still loads', flush=True)
        print('PASS Single-image cache replaces/reclaims old image; another window retains its own image', flush=True)
        delay = 0.5
    elif n == 3:
        with context(state['a']):
            bpy.context.preferences.view.language = 'zh_CN'
            bpy.context.preferences.view.use_translate_interface = True
            bpy.ops.wm.window_close()
            bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[3] / 'build/document-close.png'))
        assert state['a'] in list(bpy.context.window_manager.windows)
        decision('WINDOW', 'CANCEL')
        assert state['a_image_name'] in bpy.data.images
        print('PASS Cancelling window close keeps image and window', flush=True)
        with context(state['a']):
            bpy.ops.image.invert(invert_r=True)
            assert bpy.context.space_data.image.is_dirty
            bpy.ops.image.open(filepath=str(root / 'a.bmp'))
        assert documents._requests, 'Replacing dirty image skipped confirmation'
        decision('OPEN_IMAGE', 'CANCEL')
        with context(state['a']):
            assert bpy.context.space_data.image.filepath.endswith('b.bmp')
            bpy.ops.wm.window_close()
        decision('WINDOW', 'SAVE')
        delay = 0.5
    elif n == 4:
        assert state['a_image_name'] not in bpy.data.images
        assert state['other'].has_data
        assert (root / 'b.bmp').is_file()
        print('PASS Saving closes/reclaims only the requested image window', flush=True)
        state['text'] = open_window('Text')
        delay = 0.5
    elif n == 5:
        with context(state['text']):
            bpy.ops.text.open(filepath=str(root / 'text.txt'))
            text = bpy.context.space_data.text
            text.write('unsaved change\n')
            assert text.is_dirty
            bpy.ops.workspace.delete()
        decision('WORKSPACE', 'CANCEL')
        with context(state['text']):
            assert 'unsaved change' in bpy.context.space_data.text.as_string()
            bpy.ops.wm.window_close()
        decision('WINDOW', 'SAVE')
        delay = 0.5
    elif n == 6:
        assert 'unsaved change' in (root / 'text.txt').read_text(encoding='utf-8')
        if not state.get('extra_image'):
            print('PASS Text workspace removal prompts; cancellation retains edits; Save closes with disk contents intact', flush=True)
            state['extra_image'] = open_window('Image')
            return 0.5
        with context(state['extra_image']):
            bpy.ops.image.open(filepath=str(root / 'b.bmp'))
            bpy.ops.image.invert(invert_g=True)
            state['extra_image_name'] = bpy.context.space_data.image.name
        with context(state['b']):
            state['image_workspace'] = state['b'].workspace.name
            state['other_name'] = state['other'].name
            bpy.ops.image.invert(invert_g=True)
            bpy.ops.workspace.delete()
        decision('WORKSPACE', 'SAVE')
        delay = 0.5
    elif n == 7:
        assert state['image_workspace'] not in bpy.data.workspaces
        assert state['other_name'] not in bpy.data.images
        assert state['extra_image_name'] not in bpy.data.images
        print('PASS Workspace removal saves documents in both owner windows and clears their temporary caches', flush=True)
        # Exercise move, not copy: a split text editor becomes a new top-level window.
        with context(state['source']):
            bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)
        delay = 0.5
    elif n == 8:
        areas = list(state['source'].screen.areas)
        assert len(areas) == 2
        area = areas[0]
        area.type = 'TEXT_EDITOR'
        state['detach_data'] = bpy.data.texts.new('detach-fixture')
        state['detach_data'].write('buffer must survive detachment')
        area.spaces.active.text = state['detach_data']
        before = {w.as_pointer() for w in bpy.context.window_manager.windows}
        with context(state['source'], area):
            bpy.ops.screen.area_detach(cursor=(state['source'].width + 50, 200))
        state['detached'] = next(w for w in bpy.context.window_manager.windows if w.as_pointer() not in before)
        delay = 0.5
    elif n == 9:
        assert len(state['source'].screen.areas) == 1
        assert state['detached'].parent is None
        with context(state['detached']):
            assert bpy.context.space_data.text == state['detach_data']
            assert bpy.context.space_data.text.as_string() == 'buffer must survive detachment'
            bpy.ops.wm.window_close()
        decision('WINDOW', 'CANCEL')
        print('PASS Detachment moves the editor, preserves its unsaved buffer, and close still prompts', flush=True)
        with context(state['detached']):
            bpy.ops.wm.window_close()
        decision('WINDOW', 'SAVE')
        delay = 0.5
    elif n == 10:
        saving = [r for r in documents._requests.values() if r.saving]
        assert saving, 'Unnamed text did not open Save As'
        if not saving[0].saw_selector:
            return 0.1
        selectors = [(w, a) for w in bpy.context.window_manager.windows for a in w.screen.areas
                     if a.type == 'FILE_BROWSER' and a.spaces.active.active_operator]
        assert selectors
        with context(*selectors[0]):
            bpy.ops.file.cancel()
        delay = 0.3
    elif n == 11:
        if any(r.saving for r in documents._requests.values()):
            return 0.1
        assert state['detached'] in list(bpy.context.window_manager.windows)
        with context(state['detached']):
            assert bpy.context.space_data.text.as_string() == 'buffer must survive detachment'
            bpy.ops.wm.window_close(force_close=True)
        print('PASS Cancelling Save As retains unnamed text and its workspace', flush=True)
        delay = 0.2
    else:
        print('check_document_lifecycle: PASS', root, flush=True)
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


bpy.app.timers.register(guarded, first_interval=0.6)
