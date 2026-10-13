# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only installed-package icon lookup, called only by the isolated worker.

Kernel32 package queries do not run shell extensions, spawn PowerShell or launch
applications. Returned files are PNG assets, not the icon of ApplicationFrameHost.
"""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

MAX_PACKAGES = 64
MAX_CHARS = 65536
MAX_MANIFEST = 1024 * 1024
MAX_ASSETS = 512


def split_app_id(app_id):
    if not isinstance(app_id, str) or not 3 <= len(app_id) <= 512 or app_id.count('!') != 1:
        return None
    family, application = app_id.split('!', 1)
    # Family = package name + publisher ID; PRAID has the manifest's Application.Id.
    if (not re.fullmatch(r'[A-Za-z0-9.-]+_[A-Za-z0-9]{1,32}', family) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', application)):
        return None
    return family, application


def _kernel():
    return c.WinDLL('kernel32', use_last_error=True)


def _installed_roots(family):
    """Bounded double-call API; installation/removal races fail closed."""
    if os.name != 'nt':
        return []
    kernel = _kernel()
    query = kernel.GetPackagesByPackageFamily
    query.argtypes = [w.LPCWSTR, c.POINTER(w.UINT), c.POINTER(w.LPWSTR), c.POINTER(w.UINT), w.LPWSTR]
    query.restype = w.LONG
    count, length = w.UINT(), w.UINT()
    status = query(family, c.byref(count), None, c.byref(length), None)
    if status != 122 or not 0 < count.value <= MAX_PACKAGES or not 0 < length.value <= MAX_CHARS:
        return []
    names = (w.LPWSTR * count.value)()
    buffer = c.create_unicode_buffer(length.value)
    if query(family, c.byref(count), names, c.byref(length), buffer) != 0:
        return []
    path_query = kernel.GetPackagePathByFullName
    path_query.argtypes = [w.LPCWSTR, c.POINTER(w.UINT), w.LPWSTR]
    path_query.restype = w.LONG
    roots = []
    for name in names[:count.value]:
        if not name or len(name) > 512:
            continue
        size = w.UINT()
        if path_query(name, c.byref(size), None) != 122 or not 0 < size.value <= 32768:
            continue
        path = c.create_unicode_buffer(size.value)
        if path_query(name, c.byref(size), path) == 0 and os.path.isabs(path.value):
            roots.append(path.value)
    return roots


def _inside(root, path):
    try:
        value = path.resolve()
        return value if value != root and os.path.commonpath((str(root), str(value))) == str(root) else None
    except (OSError, ValueError, RuntimeError):
        return None


def _asset(root, relative):
    if not isinstance(relative, str) or not 1 <= len(relative) <= 256:
        return None
    value = relative.replace('\\', '/')
    parts = value.split('/')
    if (any(part in ('', '.', '..') for part in parts) or
            any(character in value for character in ':\x00%"|?*<>')):
        return None
    return _inside(root, root.joinpath(*parts))


def _png_size(path):
    try:
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            return None
        with path.open('rb') as stream:
            header = stream.read(24)
        if len(header) != 24 or header[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
            return None
        width, height = struct.unpack('>II', header[16:24])
        return (width, height) if 0 < width <= 1024 and 0 < height <= 1024 else None
    except OSError:
        return None


def _variants(root, asset):
    """Inspect one bounded asset directory, never recursively walk WindowsApps."""
    if asset.suffix.lower() != '.png':
        return []
    pattern = re.compile(re.escape(asset.stem) + r'(?:\.(.+))?\.png$', re.IGNORECASE)
    rows, visited = [], set()
    def consider(path):
        normalized = str(path).lower()
        if normalized in visited:
            return
        visited.add(normalized)
        match = pattern.fullmatch(path.name)
        if not match:
            return
        qualifiers = (match.group(1) or '').lower()
        # High-contrast/inverted theme assets can disappear on ordinary themes.
        if 'contrast-' in qualifiers or 'altform-lightunplated' in qualifiers:
            return
        path = _inside(root, path)
        dimensions = _png_size(path) if path else None
        if dimensions is None:
            return
        pixels = min(dimensions)
        unplated = 'altform-unplated' in qualifiers
        target = 'targetsize-' in qualifiers
        score = (pixels >= 32, unplated, target, min(pixels, 256), -abs(pixels - 256), path.name)
        rows.append((score, str(path)))
    # Probe the documented names directly. Some packages have thousands of
    # unrelated localized assets; their icon must not depend on directory order.
    consider(asset)
    for size in (16, 24, 32, 48, 64, 96, 256):
        for suffix in ('', '_altform-unplated'):
            consider(asset.with_name(asset.stem + '.targetsize-' + str(size) + suffix + '.png'))
    for scale in (100, 125, 150, 200, 300, 400):
        consider(asset.with_name(asset.stem + '.scale-' + str(scale) + '.png'))
    try:
        with os.scandir(asset.parent) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_ASSETS:
                    break
                consider(Path(entry.path))
    except OSError:
        pass
    return rows


def _manifest_asset(root, application):
    manifest = _inside(root, root / 'AppxManifest.xml')
    if manifest is None:
        return []
    try:
        with manifest.open('rb') as stream:
            data = stream.read(MAX_MANIFEST + 1)
        if len(data) > MAX_MANIFEST:
            return []
        encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        decoded = data.decode(encoding)
        if '<!DOCTYPE' in decoded.upper() or '<!ENTITY' in decoded.upper() or '\x00' in decoded:
            return []
        package = ET.fromstring(data)
    except (OSError, ET.ParseError, ValueError, UnicodeError):
        return []
    # Match the exact application; a package may contain multiple different apps.
    for applications in package:
        if applications.tag.rsplit('}', 1)[-1] != 'Applications':
            continue
        for app in applications:
            if app.tag.rsplit('}', 1)[-1] != 'Application' or app.get('Id') != application:
                continue
            for visual in app:
                if visual.tag.rsplit('}', 1)[-1] != 'VisualElements':
                    continue
                for attribute in ('Square44x44Logo', 'SmallLogo', 'Square30x30Logo', 'Logo', 'Square150x150Logo'):
                    asset = _asset(root, visual.get(attribute))
                    if asset is not None:
                        candidates = _variants(root, asset)
                        if candidates:
                            return candidates
    return []


def resolve(app_id):
    """Return the installed application's real PNG, or None without side effects."""
    identity = split_app_id(app_id)
    if identity is None:
        return None
    family, application = identity
    try:
        candidates = []
        for root in _installed_roots(family):
            path = Path(root).resolve()
            if path.is_dir():
                candidates.extend(_manifest_asset(path, application))
        return max(candidates)[1] if candidates else None
    except (OSError, ValueError, RuntimeError, AttributeError):
        return None
