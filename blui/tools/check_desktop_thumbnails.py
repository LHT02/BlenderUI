# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the exact native File Browser thumbnail pipeline without launching BLUI UI.

Run: bundled Python -B check_desktop_thumbnails.py <newly built BLUI.exe>
All source files and reply files are private temporary fixtures. No bpy/UI or user file opens.
"""
import base64
import ctypes
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts/modules'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blui_desktop import thumbnails
from test_desktop_background import png_rgba


def blend_thumb(width, height, top_down):
    stride = width * 4
    bottom_up = b''.join(top_down[row * stride:(row + 1) * stride] for row in reversed(range(height)))
    data = struct.pack('<ii', width, height) + bottom_up
    return b'BLENDER-v400' + struct.pack('<4siQii', b'TEST', len(data), 0, 0, 1) + data


def avi(width=16, height=16):
    def chunk(kind, payload):
        return kind + struct.pack('<I', len(payload)) + payload + bytes(len(payload) % 2)
    def listing(kind, payload):
        return chunk(b'LIST', kind + payload)
    frame = b''.join(bytes((255, 0, 0) if row < height // 2 else (0, 0, 255)) * width
                     for row in range(height))
    avih = struct.pack('<14I', 40000, len(frame) * 25, 0, 0x10, 1, 0, 1,
                       len(frame), width, height, 0, 0, 0, 0)
    strh = struct.pack('<4s4sIHH8I4h', b'vids', b'DIB ', 0, 0, 0,
                       0, 1, 25, 0, 1, len(frame), 0xffffffff, 0, 0, 0, width, height)
    strf = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, len(frame), 0, 0, 0, 0)
    hdrl = listing(b'hdrl', chunk(b'avih', avih) + listing(b'strl', chunk(b'strh', strh) + chunk(b'strf', strf)))
    body = b'AVI ' + hdrl + listing(b'movi', chunk(b'00db', frame)) + chunk(b'idx1', struct.pack('<4sIII', b'00db', 0x10, 4, len(frame)))
    return chunk(b'RIFF', body)


def inspect(runner, paths):
    with mock.patch.object(thumbnails, 'executable', return_value=str(runner)):
        rows = thumbnails.extract([str(path) for path in paths])
    thumbnails.validate_pixels(rows)
    return rows


def pixels(row):
    return base64.b64decode(row['rgba'], validate=True)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: check_desktop_thumbnails.py <BLUI.exe>')
    runner = Path(sys.argv[1]).resolve(strict=True)
    # An older BLUI treats unknown flags as regular startup. Never accidentally launch its UI.
    if b'--blui-file-preview' not in runner.read_bytes():
        raise RuntimeError('Rebuild BLUI before running the dedicated preview helper fixture')
    checks = 0
    with tempfile.TemporaryDirectory(prefix='blui_native_preview_') as directory:
        root = Path(directory)
        image = root / '透明与方向.png'
        rgba = bytes((255, 0, 0, 255)) * 16 + bytes((0, 0, 255, 128)) * 16
        image.write_bytes(png_rgba(8, 4, rgba))
        embedded = root / 'Embedded.blend'
        embedded.write_bytes(blend_thumb(8, 4, rgba))
        rows = inspect(runner, [image, embedded])
        for row in rows:
            assert (row['width'], row['height']) == (8, 4), row
            result = pixels(row)
            assert result[:4] == rgba[:4] and result[-4:] == rgba[-4:], (row['path'], result[:4], result[-4:])
            checks += 1
        print('NATIVE_THUMBNAILS image alpha/orientation + embedded Blend PASS', flush=True)

        # The existing File Browser cache validates source MTime and regenerates, not sticky path-only.
        old_time = image.stat().st_mtime
        changed = bytes((0, 255, 0, 255)) * 32
        image.write_bytes(png_rgba(8, 4, changed))
        os.utime(image, (old_time + 2, old_time + 2))
        refreshed = inspect(runner, [image])[0]
        assert pixels(refreshed) == changed, refreshed
        checks += 1
        print('NATIVE_THUMBNAILS existing mtime cache invalidation PASS', flush=True)

        # An offline cloud placeholder is represented by Windows' FILE_ATTRIBUTE_OFFLINE.
        # On a private normal file, the same gate must read the prior cache, not source bytes.
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
        kernel.GetFileAttributesW.restype = ctypes.c_uint32
        kernel.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        kernel.SetFileAttributesW.restype = ctypes.c_int
        original_attributes = kernel.GetFileAttributesW(str(image))
        image.write_bytes(png_rgba(8, 4, bytes((255, 255, 0, 255)) * 32))
        os.utime(image, (old_time + 4, old_time + 4))
        assert kernel.SetFileAttributesW(str(image), original_attributes | 0x1000), ctypes.get_last_error()
        try:
            offline = inspect(runner, [image])[0]
            assert pixels(offline) == changed, 'Offline file was decoded instead of using the existing cache'
            checks += 1
        finally:
            kernel.SetFileAttributesW(str(image), original_attributes)
        print('NATIVE_THUMBNAILS offline cache-only/no source hydration gate PASS', flush=True)

        large = root / 'Wide.png'
        large.write_bytes(png_rgba(800, 400, bytes((30, 100, 240, 255)) * 800 * 400))
        wide = inspect(runner, [large])[0]
        assert (wide['width'], wide['height']) == (256, 128), wide
        checks += 1

        video = root / 'Frame.avi'
        video.write_bytes(avi())
        movie = inspect(runner, [video])[0]
        assert (movie['width'], movie['height']) == (16, 16), movie
        data = pixels(movie)
        assert data[0] > 200 and data[2] < 30 and data[-4] < 30 and data[-2] > 200, (data[:4], data[-4:])
        checks += 1
        print('NATIVE_THUMBNAILS image scaling + real AVI frame PASS', flush=True)

        font = root / 'Typeface.ttf'
        shutil.copy2(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/arial.ttf', font)
        glyphs = inspect(runner, [font])[0]
        assert (glyphs['width'], glyphs['height']) == (256, 256), glyphs
        alpha = pixels(glyphs)[3::4]
        assert max(alpha) > 0 and min(alpha) == 0, 'No transparent font preview'
        checks += 1
        print('NATIVE_THUMBNAILS real FreeType font PASS', flush=True)

        bad = root / 'Broken.png'
        bad.write_bytes(b'not an image')
        for path in (bad, root / 'Missing.mp4', root / 'Shortcut.lnk', root / 'Notes.txt'):
            result = inspect(runner, [path])[0]
            assert result == thumbnails.empty(str(path)), result
            checks += 1
        reply = root / 'must-not-exist.rgba'
        invalid = subprocess.run([str(runner), '--blui-file-preview', 'relative.png', str(reply)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=4, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert invalid.returncode == 2 and not reply.exists(), invalid.returncode
        checks += 1
        # Read-only monitor of this exact helper PID: background preview must not create even
        # a hidden GHOST/BLUI window or tray host (not just immediately close a blank window).
        user = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t)
        user.EnumWindows.argtypes = [callback_type, ctypes.c_ssize_t]
        user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        owned_windows = []
        process = subprocess.Popen([str(runner), '--blui-file-preview', str(large), str(reply)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        @callback_type
        def collect(hwnd, unused):
            pid = ctypes.c_uint32()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == process.pid:
                owned_windows.append(int(hwnd))
            return 1
        deadline = time.monotonic() + 4
        while process.poll() is None and time.monotonic() < deadline:
            user.EnumWindows(collect, 0)
            time.sleep(.005)
        if process.poll() is None:
            process.kill()
        assert process.wait(timeout=1) == 0 and not owned_windows, owned_windows
        checks += 1
        print('NATIVE_THUMBNAILS malformed/missing/nonpreview/relative fallback PASS', flush=True)
    print('NATIVE_THUMBNAILS PASS:', checks, 'checks; no GUI, private fixtures only', flush=True)


if __name__ == '__main__':
    main()
