# SPDX-License-Identifier: GPL-2.0-or-later
"""Desktop wallpapers: isolated decoding, bounded pixel cache and native PRE_VIEW drawing.

This module deliberately has no top-level bpy/gpu imports so its validation,
decoder and placement math can run in disposable service processes and tests.
Wallpaper alpha reveals the BLUI canvas; it does not make the OS window transparent.
"""
import base64
from collections import OrderedDict
import math
import os
import struct
import zlib

FITS = {'FIT', 'FILL', 'STRETCH', 'CENTER', 'TILE', 'SPAN'}
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_PIXELS = 32 * 1024 * 1024
MAX_TEXTURE_PIXELS = 4 * 1024 * 1024
MAX_COMPRESSED_BYTES = 6 * 1024 * 1024 - 4096
MAX_CACHE_BYTES = 64 * 1024 * 1024
MAX_CACHE_ENTRIES = 8
MAX_QUADS = 4096
_cache = OrderedDict()
_handler = None
_shader = None
_monitor_provider = None


def validate_settings(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid desktop background settings')
    result = {'enabled': value.get('enabled', False), 'path': value.get('path', ''),
              'opacity': value.get('opacity', 1.0), 'fit': value.get('fit', 'FILL'),
              'align_x': value.get('align_x', 0.0), 'align_y': value.get('align_y', 0.0)}
    if (type(result['enabled']) is not bool or
            not isinstance(result['path'], str) or len(result['path']) > 32768 or
            '\x00' in result['path'] or not isinstance(result['fit'], str) or result['fit'] not in FITS):
        raise ValueError('Invalid desktop background settings')
    for field, low, high in (('opacity', 0.0, 1.0), ('align_x', -1.0, 1.0), ('align_y', -1.0, 1.0)):
        number = result[field]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError('Invalid desktop background position or opacity')
    return result


def settings(tree):
    return validate_settings({key: getattr(tree, 'background_' + key) for key in
                              ('enabled', 'path', 'opacity', 'fit', 'align_x', 'align_y')})


def _size(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(type(item) not in (int, float) or not math.isfinite(item) or
                not 0 < item <= 1000000 for item in value)):
        raise ValueError('Invalid desktop background size')
    return value


def _crop(quad, viewport):
    """Clip a (rect, UV) pair in bottom-left pixel coordinates, retaining original UVs."""
    rect, uv = quad
    left, bottom, right, top = rect
    x0, y0, x1, y1 = viewport
    cx0, cy0, cx1, cy1 = max(left, x0), max(bottom, y0), min(right, x1), min(top, y1)
    if cx1 <= cx0 or cy1 <= cy0:
        return None
    u0, v0, u1, v1 = uv
    du, dv = (u1 - u0) / (right - left), (v1 - v0) / (top - bottom)
    return ((cx0, cy0, cx1, cy1),
            (u0 + (cx0 - left) * du, v0 + (cy0 - bottom) * dv,
             u0 + (cx1 - left) * du, v0 + (cy1 - bottom) * dv))


def placements(image_size, viewport_size, fit='FILL', align_x=0.0, align_y=0.0,
               *, virtual_rect=None, monitor_rect=None):
    """Return bounded clipped rect/UV quads, never mixing Win32/DPI logical coordinates.

    SPAN maps this region onto one physical monitor rectangle of a physical
    virtual desktop; region dimensions may differ because of DPI or window size.
    Alignment -1/0/+1 means left/center/right and bottom/center/top respectively.
    """
    width, height = _size(image_size)
    view_w, view_h = _size(viewport_size)
    validate_settings({'fit': fit, 'align_x': align_x, 'align_y': align_y})
    virtual = (0, 0, view_w, view_h)
    monitor = virtual
    if fit == 'SPAN' and virtual_rect is not None and monitor_rect is not None:
        for value in (virtual_rect, monitor_rect):
            if (not isinstance(value, (list, tuple)) or len(value) != 4 or any(
                    type(item) not in (int, float) or not math.isfinite(item) or abs(item) > 1e6
                    for item in value) or value[2] <= value[0] or value[3] <= value[1]):
                raise ValueError('Invalid desktop background monitor rectangle')
        vl, vt, vr, vb = virtual_rect
        ml, mt, mr, mb = monitor_rect
        if not (vl <= ml < mr <= vr and vt <= mt < mb <= vb):
            raise ValueError('Desktop background monitor is outside the virtual desktop')
        # Win32 top-left origin becomes bottom-left before UV computation.
        virtual = (0, 0, vr - vl, vb - vt)
        monitor = (ml - vl, vb - mb, mr - vl, vb - mt)
    extent_w, extent_h = virtual[2], virtual[3]
    if fit == 'STRETCH':
        drawn_w, drawn_h = extent_w, extent_h
    elif fit in {'FIT', 'FILL', 'SPAN'}:
        ratio = (min if fit == 'FIT' else max)(extent_w / width, extent_h / height)
        drawn_w, drawn_h = width * ratio, height * ratio
    else:
        drawn_w, drawn_h = width, height
    left = (extent_w - drawn_w) * (align_x + 1) / 2
    bottom = (extent_h - drawn_h) * (align_y + 1) / 2
    rows = []
    if fit == 'TILE':
        # Centre tiles are aligned like other modes. Extremely small source
        # images are represented by one repeated-UV quad, not millions of draws.
        tiles_x = math.ceil(view_w / drawn_w) + 2
        tiles_y = math.ceil(view_h / drawn_h) + 2
        if tiles_x * tiles_y > MAX_QUADS:
            return [((0, 0, view_w, view_h),
                     (-left / drawn_w, -bottom / drawn_h,
                      (view_w - left) / drawn_w, (view_h - bottom) / drawn_h))]
        start_x, start_y = math.floor(-left / drawn_w), math.floor(-bottom / drawn_h)
        for y in range(start_y, start_y + tiles_y):
            for x in range(start_x, start_x + tiles_x):
                x0, y0 = left + x * drawn_w, bottom + y * drawn_h
                row = _crop(((x0, y0, x0 + drawn_w, y0 + drawn_h), (0, 0, 1, 1)), monitor)
                if row:
                    rows.append(row)
    else:
        row = _crop(((left, bottom, left + drawn_w, bottom + drawn_h), (0, 0, 1, 1)), monitor)
        if row:
            rows.append(row)
    scale_x, scale_y = view_w / (monitor[2] - monitor[0]), view_h / (monitor[3] - monitor[1])
    return [(((r[0] - monitor[0]) * scale_x, (r[1] - monitor[1]) * scale_y,
              (r[2] - monitor[0]) * scale_x, (r[3] - monitor[1]) * scale_y), uv) for r, uv in rows]


def _header(path):
    stat = os.stat(path)
    if not 0 < stat.st_size <= MAX_FILE_BYTES:
        raise ValueError('Desktop background file is too large')
    with open(path, 'rb') as source:
        header = source.read(min(stat.st_size, 1024 * 1024))
    if header.startswith(b'\x89PNG\r\n\x1a\n') and len(header) >= 29 and header[12:16] == b'IHDR':
        width, height = struct.unpack('>II', header[16:24])
    elif header.startswith(b'\xff\xd8'):
        position = 2
        width = height = 0
        while position < len(header):
            if header[position] != 0xff:
                raise ValueError('Invalid desktop background JPEG header')
            while position < len(header) and header[position] == 0xff:
                position += 1
            if position >= len(header):
                break
            marker = header[position]
            position += 1
            if marker in {0x01, *range(0xd0, 0xd9)}:
                continue
            if position + 2 > len(header):
                break
            length = struct.unpack('>H', header[position:position + 2])[0]
            if length < 2 or position + length > len(header):
                break
            if marker in {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}:
                if length < 8:
                    break
                height, width = struct.unpack('>HH', header[position + 3:position + 7])
                break
            if marker in {0xda, 0xd9}:
                break
            position += length
    else:
        raise ValueError('Desktop backgrounds support PNG and JPEG images')
    if not width or not height or width > 32768 or height > 32768 or width * height > MAX_SOURCE_PIXELS:
        raise ValueError('Desktop background dimensions are too large or invalid')
    return width, height


def _decode(path, source_size):
    """GDI+ runs only in the owned disposable worker, not Blender's native decoder."""
    import ctypes as c
    from ctypes import wintypes as w
    import numpy as np

    class Startup(c.Structure):
        _fields_ = [('version', w.UINT), ('debug', c.c_void_p),
                    ('suppress_thread', w.BOOL), ('suppress_codecs', w.BOOL)]

    class Rect(c.Structure):
        _fields_ = [('x', c.c_int), ('y', c.c_int), ('width', c.c_int), ('height', c.c_int)]

    class BitmapData(c.Structure):
        _fields_ = [('width', w.UINT), ('height', w.UINT), ('stride', c.c_int),
                    ('format', c.c_int), ('pixels', c.c_void_p), ('reserved', c.c_size_t)]

    dll = c.WinDLL('gdiplus')
    signatures = {
        'GdiplusStartup': ([c.POINTER(c.c_size_t), c.POINTER(Startup), c.c_void_p], c.c_int),
        'GdiplusShutdown': ([c.c_size_t], None),
        'GdipCreateBitmapFromFile': ([w.LPCWSTR, c.POINTER(c.c_void_p)], c.c_int),
        'GdipGetImageWidth': ([c.c_void_p, c.POINTER(w.UINT)], c.c_int),
        'GdipGetImageHeight': ([c.c_void_p, c.POINTER(w.UINT)], c.c_int),
        'GdipCreateBitmapFromScan0': ([c.c_int, c.c_int, c.c_int, c.c_int, c.c_void_p,
                                      c.POINTER(c.c_void_p)], c.c_int),
        'GdipGetImageGraphicsContext': ([c.c_void_p, c.POINTER(c.c_void_p)], c.c_int),
        'GdipSetInterpolationMode': ([c.c_void_p, c.c_int], c.c_int),
        'GdipSetCompositingMode': ([c.c_void_p, c.c_int], c.c_int),
        'GdipDrawImageRectI': ([c.c_void_p, c.c_void_p, c.c_int, c.c_int, c.c_int, c.c_int], c.c_int),
        'GdipBitmapLockBits': ([c.c_void_p, c.POINTER(Rect), w.UINT, c.c_int,
                                c.POINTER(BitmapData)], c.c_int),
        'GdipBitmapUnlockBits': ([c.c_void_p, c.POINTER(BitmapData)], c.c_int),
        'GdipDeleteGraphics': ([c.c_void_p], c.c_int),
        'GdipDisposeImage': ([c.c_void_p], c.c_int),
    }
    for name, (args, result) in signatures.items():
        function = getattr(dll, name)
        function.argtypes, function.restype = args, result

    def check(result):
        if result:
            raise ValueError('Desktop background image could not be decoded')

    token, image = c.c_size_t(), c.c_void_p()
    check(dll.GdiplusStartup(c.byref(token), c.byref(Startup(1, None, False, False)), None))
    try:
        check(dll.GdipCreateBitmapFromFile(path, c.byref(image)))
        width, height = w.UINT(), w.UINT()
        check(dll.GdipGetImageWidth(image, c.byref(width)))
        check(dll.GdipGetImageHeight(image, c.byref(height)))
        if (width.value, height.value) != tuple(source_size):
            raise ValueError('Desktop background image changed during loading')
        ratio = min(1.0, math.sqrt(MAX_TEXTURE_PIXELS / (width.value * height.value)))
        for attempt in range(5):
            target = c.c_void_p()
            graphics = c.c_void_p()
            target_w, target_h = max(1, round(width.value * ratio)), max(1, round(height.value * ratio))
            # Straight (not premultiplied) ARGB preserves transparent PNG edges.
            pixel_format = 0x26200a
            try:
                check(dll.GdipCreateBitmapFromScan0(target_w, target_h, 0, pixel_format,
                                                    None, c.byref(target)))
                check(dll.GdipGetImageGraphicsContext(target, c.byref(graphics)))
                check(dll.GdipSetInterpolationMode(graphics, 7))  # High-quality bicubic.
                check(dll.GdipSetCompositingMode(graphics, 1))  # SourceCopy retains alpha.
                check(dll.GdipDrawImageRectI(graphics, image, 0, 0, target_w, target_h))
                dll.GdipDeleteGraphics(graphics)
                graphics = c.c_void_p()
                bitmap = BitmapData()
                check(dll.GdipBitmapLockBits(target, c.byref(Rect(0, 0, target_w, target_h)),
                                               1, pixel_format, c.byref(bitmap)))
                try:
                    if (bitmap.width != target_w or bitmap.height != target_h or
                            abs(bitmap.stride) < target_w * 4 or not bitmap.pixels):
                        raise ValueError('Invalid desktop background pixel stride')
                    raw = b''.join(c.string_at(bitmap.pixels + y * bitmap.stride, target_w * 4)
                                   for y in range(target_h))
                finally:
                    dll.GdipBitmapUnlockBits(target, c.byref(bitmap))
                rgba = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 4)[:, [2, 1, 0, 3]].tobytes()
                compressed = zlib.compress(rgba, 3)
                if len(compressed) <= MAX_COMPRESSED_BYTES:
                    return target_w, target_h, base64.b64encode(compressed).decode('ascii')
                ratio *= .75  # Bound IPC size even for incompressible noise images.
            finally:
                if graphics:
                    dll.GdipDeleteGraphics(graphics)
                if target:
                    dll.GdipDisposeImage(target)
        raise ValueError('Desktop background pixel response is too large')
    finally:
        if image:
            dll.GdipDisposeImage(image)
        dll.GdiplusShutdown(token)


def inspect(path):
    if os.name != 'nt':
        raise RuntimeError('Desktop background decoding requires Windows')
    if not isinstance(path, str) or not path or len(path) > 32768 or '\x00' in path:
        raise ValueError('Invalid desktop background path')
    path = os.path.abspath(path)
    original = _header(path)
    width, height, compressed = _decode(path, original)
    return {'path': path, 'width': width, 'height': height,
            'source_width': original[0], 'source_height': original[1], 'rgba_zlib': compressed}


def validate_pixels(value, *, decompress=False):
    if not isinstance(value, dict) or not isinstance(value.get('path'), str) or not value['path'] or \
            len(value['path']) > 32768 or '\x00' in value['path']:
        raise ValueError('Invalid desktop background response')
    for field in ('width', 'height', 'source_width', 'source_height'):
        if type(value.get(field)) is not int or not 0 < value[field] <= 32768:
            raise ValueError('Invalid desktop background dimensions')
    expected = value['width'] * value['height'] * 4
    if expected > MAX_TEXTURE_PIXELS * 4 or value['source_width'] * value['source_height'] > MAX_SOURCE_PIXELS:
        raise ValueError('Desktop background response is too large')
    encoded = value.get('rgba_zlib')
    if not isinstance(encoded, str) or len(encoded) > ((MAX_COMPRESSED_BYTES + 2) // 3) * 4:
        raise ValueError('Desktop background response is too large')
    compressed = base64.b64decode(encoded, validate=True)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise ValueError('Desktop background response is too large')
    decoder = zlib.decompressobj()
    pixels = decoder.decompress(compressed, expected + 1)
    if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Invalid desktop background pixel data')
    return pixels if decompress else value


def _key(tree):
    return tree.as_pointer(), tree.service_identity


def apply(tree, value):
    """Main thread, once per completed job: only validated RAM pixels reach GPU/RNA."""
    import gpu
    import numpy as np
    raw = validate_pixels(value, decompress=True)
    width, height = value['width'], value['height']
    pixels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)[::-1].astype(np.float32)
    pixels *= 1.0 / 255.0
    buffer = gpu.types.Buffer('FLOAT', (height, width, 4), pixels)
    texture = gpu.types.GPUTexture((width, height), format='RGBA8', data=buffer)
    key = _key(tree)
    _cache[key] = {'texture': texture, 'width': width, 'height': height,
                   'source_width': value['source_width'], 'source_height': value['source_height'],
                   'bytes': len(raw), 'path': value['path'], 'batch_key': None, 'batch': None,
                   'draw_count': 0, 'error': ''}
    _cache.move_to_end(key)
    while len(_cache) > MAX_CACHE_ENTRIES or sum(item['bytes'] for item in _cache.values()) > MAX_CACHE_BYTES:
        _cache.popitem(last=False)
    tree.background_path = value['path']
    tree.background_enabled = True


def has_image(tree):
    try:
        entry = _cache.get(_key(tree))
        return bool(entry and entry['path'] == tree.background_path)
    except (AttributeError, ReferenceError):
        return False


def diagnostics(tree):
    entry = _cache.get(_key(tree))
    return {'draw_count': entry['draw_count'], 'error': entry['error']} if entry else None


def clear(tree=None):
    if tree is None:
        _cache.clear()
    else:
        _cache.pop(_key(tree), None)


def _display_rects(tree):
    if _monitor_provider is None:
        return None, None
    snapshot = _monitor_provider()
    rows = snapshot.get('monitors', []) if isinstance(snapshot, dict) else []
    current = next((row for row in rows if row['device'] == tree.monitor), None)
    if current is None:
        return None, None
    rects = [row['rect'] for row in rows]
    return ((min(row[0] for row in rects), min(row[1] for row in rects),
             max(row[2] for row in rects), max(row[3] for row in rects)), current['rect'])


def _draw():
    global _shader
    import bpy
    import gpu
    from mathutils import Matrix
    from gpu_extras.batch import batch_for_shader
    context = bpy.context
    space, region = context.space_data, context.region
    if not space or space.type != 'NODE_EDITOR' or not region:
        return
    tree = space.node_tree  # Root board owns wallpaper while inside nested groups.
    if not tree or tree.bl_idname != 'BLUIDesktopTree' or not tree.background_enabled:
        return
    entry = _cache.get(_key(tree))
    if not entry or entry['path'] != tree.background_path or tree.background_opacity <= 0:
        return
    previous_blend = None
    try:
        virtual, monitor = _display_rects(tree) if tree.background_fit == 'SPAN' else (None, None)
        batch_key = (region.width, region.height, tree.background_fit, tree.background_align_x,
                     tree.background_align_y, virtual, tuple(monitor) if monitor else None)
        if _shader is None:
            # This fork predates Python texture wrap_mode/filter_mode. Repeat is
            # explicit in the shader, including a one-quad small-image tile path.
            _shader = gpu.types.GPUShader(
                'uniform mat4 ModelViewProjectionMatrix; in vec3 pos; in vec2 texCoord; '
                'out vec2 uv; void main(){uv=texCoord; '
                'gl_Position=ModelViewProjectionMatrix*vec4(pos,1.0);}',
                'uniform sampler2D image; uniform vec4 color; uniform bool tiled; '
                'in vec2 uv; out vec4 fragColor; void main(){'
                'fragColor=texture(image,tiled?fract(uv):uv)*color;}')
        if entry['batch_key'] != batch_key:
            rows = placements((entry['source_width'], entry['source_height']),
                              (region.width, region.height), tree.background_fit,
                              tree.background_align_x, tree.background_align_y,
                              virtual_rect=virtual, monitor_rect=monitor)
            positions, coordinates, indices = [], [], []
            for rect, uv in rows:
                left, bottom, right, top = rect
                u0, v0, u1, v1 = uv
                offset = len(positions)
                positions.extend(((left, bottom, 0), (right, bottom, 0),
                                  (right, top, 0), (left, top, 0)))
                coordinates.extend(((u0, v0), (u1, v0), (u1, v1), (u0, v1)))
                indices.extend(((offset, offset + 1, offset + 2), (offset, offset + 2, offset + 3)))
            entry['batch'] = batch_for_shader(_shader, 'TRIS',
                                              {'pos': positions, 'texCoord': coordinates}, indices=indices) if rows else None
            entry['batch_key'] = batch_key
        if entry['batch'] is None:
            return
        previous_blend = gpu.state.blend_get()
        gpu.state.blend_set('ALPHA')
        # PRE_VIEW has the canvas's panned/zoomed projection. Wallpapers instead
        # stay attached to the window; both matrices are restored before nodes draw.
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_matrix(Matrix.Identity(4))
            gpu.matrix.load_projection_matrix(Matrix(((2 / region.width, 0, 0, -1),
                                                      (0, 2 / region.height, 0, -1),
                                                      (0, 0, -1, 0), (0, 0, 0, 1))))
            _shader.bind()
            _shader.uniform_sampler('image', entry['texture'])
            _shader.uniform_float('color', (1, 1, 1, tree.background_opacity))
            _shader.uniform_bool('tiled', tree.background_fit == 'TILE')
            entry['batch'].draw(_shader)
            entry['draw_count'] += 1
            entry['error'] = ''
    except (ReferenceError, RuntimeError, ValueError, AttributeError, TypeError) as error:
        # A context loss, removed board or monitor change must not break redraw.
        # No RNA writes or path queries are performed in this callback.
        entry['error'] = str(error)
        return
    finally:
        if previous_blend is not None:
            gpu.state.blend_set(previous_blend)


def register(monitor_provider=None):
    global _handler, _monitor_provider
    import bpy
    _monitor_provider = monitor_provider
    if _handler is None:
        _handler = bpy.types.SpaceNodeEditor.draw_handler_add(_draw, (), 'WINDOW', 'PRE_VIEW')


def unregister():
    global _handler, _shader, _monitor_provider
    import bpy
    if _handler is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_handler, 'WINDOW')
    _handler, _shader, _monitor_provider = None, None, None
    clear()
