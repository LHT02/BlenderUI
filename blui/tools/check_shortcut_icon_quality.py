# SPDX-License-Identifier: GPL-2.0-or-later
"""Build private ICO/link fixtures and test native resolution, pixels, alpha, and orientation.

Run with the bundled Python and a precompiled fileicon_selftest.exe argument.
No GUI, link invocation, user Desktop changes, or Shell cache mutations are needed.
"""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib


def color(x, y, size):
    if y < 8:
        return 0, 0, 255, 255
    if y >= size - 8:
        return 255, 0, 0, 255
    if y >= size - 14:
        return 64, 128, 192, 128
    return (255, 255, 255, 255) if x % 2 else (0, 255, 0, 255)


def bitmap(size, detailed=False):
    pixels = bytearray()
    for y in reversed(range(size)):
        for x in range(size):
            r, g, b, a = color(x, y, size) if detailed else (0, 255, 0, 255)
            pixels += bytes((b, g, r, a))
    mask = bytes(((size + 31) // 32) * 4 * size)
    return struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0,
                       len(pixels), 0, 0, 0, 0) + pixels + mask


def png(size, padded=False):
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data +
                struct.pack('>I', zlib.crc32(kind + data)))
    def pixel(x, y):
        if padded:
            return ((0, 255, 0, 255) if 120 <= x < 136 and 120 <= y < 136 else (0, 0, 0, 0))
        return color(x, y, size)
    rows = b''.join(b'\x00' + bytes(channel for x in range(size)
                                   for channel in pixel(x, y)) for y in range(size))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def ico(path, entries):
    directory = bytearray(struct.pack('<HHH', 0, 1, len(entries)))
    offset = 6 + len(entries) * 16
    for size, data in entries:
        directory += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0,
                                 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(directory + b''.join(data for _, data in entries))


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != '--pe'):
        raise SystemExit('Usage: check_shortcut_icon_quality.py <fileicon_selftest.exe> [--pe]')
    runner = Path(sys.argv[1]).resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix='blui_icon_quality_'))
    (root / 'target.txt').write_text('Private icon test fixture', encoding='utf-8')
    ico(root / 'PNG.ico', [(16, bitmap(16)), (48, bitmap(48)), (256, png(256))])
    ico(root / 'BMP.ico', [(16, bitmap(16)), (64, bitmap(64, detailed=True))])
    ico(root / 'Small.ico', [(16, bitmap(16))])
    ico(root / 'Padded.ico', [(256, png(256, padded=True))])
    ico(root / 'Damaged.ico', [(256, b'invalid frame'), (32, bitmap(32))])
    environment = dict(os.environ, BLUI_ICON_QUALITY_FIXTURE=str(root))
    pe = len(sys.argv) == 3
    if pe:
        if not shutil.which('rc.exe') or not shutil.which('cl.exe'):
            raise RuntimeError('--pe requires the Visual Studio developer PowerShell environment')
        (root / 'Fixture.rc').write_text('17 ICON "PNG.ico"\n23 ICON "BMP.ico"\n', encoding='utf-8')
        (root / 'Fixture.c').write_text('''
#include <windows.h>
BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        wchar_t path[32768];
        DWORD length = GetEnvironmentVariableW(L"BLUI_ICON_QUALITY_FIXTURE", path, 32740);
        if (length && length < 32740) {
            lstrcatW(path, L"\\\\executed.txt");
            HANDLE file = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_NEW,
                                      FILE_ATTRIBUTE_NORMAL, NULL);
            if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
        }
    }
    return TRUE;
}
''', encoding='utf-8')
        subprocess.run(['rc.exe', '/nologo', '/fo', 'Fixture.res', 'Fixture.rc'],
                       cwd=root, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run(['cl.exe', '/nologo', '/LD', '/utf-8', 'Fixture.c', 'Fixture.res',
                        '/Fe:Fixture.dll', '/Fo:Fixture.obj', '/link', '/INCREMENTAL:NO'],
                       cwd=root, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run(['pwsh', '-NoProfile', '-Command', '''
$ErrorActionPreference = 'Stop'
$fixtureRoot = $env:BLUI_ICON_QUALITY_FIXTURE
$linkFactory = New-Object -ComObject WScript.Shell
foreach ($iconName in @('PNG', 'BMP', 'Small', 'Padded', 'Damaged', 'Environment')) {
    $fixtureLink = $linkFactory.CreateShortcut((Join-Path $fixtureRoot ($iconName + '.lnk')))
    $fixtureLink.TargetPath = Join-Path $fixtureRoot 'target.txt'
    $fixtureLink.IconLocation = if ($iconName -eq 'Environment') {
        '%BLUI_ICON_QUALITY_FIXTURE%\\PNG.ico,0'
    } else { (Join-Path $fixtureRoot ($iconName + '.ico')) + ',0' }
    $fixtureLink.Save()
}
if (Test-Path -LiteralPath (Join-Path $fixtureRoot 'Fixture.dll')) {
    foreach ($peName in @('PE', 'PEIndex', 'PETarget')) {
        $fixtureLink = $linkFactory.CreateShortcut((Join-Path $fixtureRoot ($peName + '.lnk')))
        $fixtureLink.TargetPath = Join-Path $fixtureRoot 'Fixture.dll'
        if ($peName -ne 'PETarget') {
            $fixtureLink.IconLocation = (Join-Path $fixtureRoot 'Fixture.dll') + $(if ($peName -eq 'PE') { ',-17' } else { ',1' })
        }
        $fixtureLink.Save()
    }
}
'''], env=environment, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    result = subprocess.run([str(runner), str(root)], env=environment, check=False)
    print('Icon quality fixture:', root, flush=True)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
