# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate BLUI's brand art: the splash screen and the logo.

Both are embedded into the executable at build time by `data_to_c_simple`, so
they are what a user actually sees on start-up. The inherited artwork is
Blender's, which is why a stock fork still "looks like Blender" no matter what
the binary is called.

Pixels are written directly through `foreach_set`, so this runs fine in
`--background` mode with no GPU or render engine involved.

Run with:
    BLUI.exe --background --python tools/make_brand_art.py -- --outdir <dir>
"""

import os
import sys

import bpy

# 5x7 bitmap glyphs, one string per row, '1' = ink.
FONT = {
    "B": ["11100", "10010", "10010", "11100", "10010", "10010", "11100"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11110"],
    "U": ["10010", "10010", "10010", "10010", "10010", "10010", "01100"],
    "I": ["11100", "01000", "01000", "01000", "01000", "01000", "11100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}

INK = (0.93, 0.95, 0.98)
ACCENT = (0.16, 0.72, 0.85)
BG_TOP = (0.043, 0.055, 0.075)
BG_BOTTOM = (0.094, 0.129, 0.180)


def _parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    if "--outdir" not in argv:
        raise SystemExit("make_brand_art.py: --outdir <dir> is required")
    return argv[argv.index("--outdir") + 1]


def _text_extent(text, scale):
    width = 0
    for ch in text:
        width += len(FONT[ch][0]) * scale + 2 * scale
    return width - 2 * scale, 7 * scale


def _blit_text(buf, img_w, img_h, text, scale, origin_x, origin_y, color):
    """Draw `text` with its bottom-left corner at (origin_x, origin_y)."""
    pen = origin_x
    for ch in text:
        glyph = FONT[ch]
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit != "1":
                    continue
                # Row 0 of the glyph is the top, but image rows run bottom-up.
                py0 = origin_y + (6 - row) * scale
                px0 = pen + col * scale
                for y in range(py0, py0 + scale):
                    if y < 0 or y >= img_h:
                        continue
                    base = (y * img_w + px0) * 4
                    for x in range(px0, px0 + scale):
                        if x < 0 or x >= img_w:
                            continue
                        off = base + (x - px0) * 4
                        buf[off] = color[0]
                        buf[off + 1] = color[1]
                        buf[off + 2] = color[2]
                        buf[off + 3] = 1.0
        pen += len(glyph[0]) * scale + 2 * scale


def _blend_text(buf, img_w, img_h, text, scale, origin_x, origin_y, color):
    """Like _blit_text but alpha-blends, preserving the background."""
    pen = origin_x
    for ch in text:
        glyph = FONT[ch]
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit != "1":
                    continue
                py0 = origin_y + (6 - row) * scale
                px0 = pen + col * scale
                for y in range(py0, py0 + scale):
                    if y < 0 or y >= img_h:
                        continue
                    for x in range(px0, px0 + scale):
                        if x < 0 or x >= img_w:
                            continue
                        off = (y * img_w + x) * 4
                        buf[off] = color[0]
                        buf[off + 1] = color[1]
                        buf[off + 2] = color[2]
                        buf[off + 3] = 1.0
        pen += len(glyph[0]) * scale + 2 * scale


def _save(buf, img_w, img_h, path):
    image = bpy.data.images.new(os.path.basename(path), img_w, img_h, alpha=True)
    image.pixels.foreach_set(buf)
    image.filepath_raw = path
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    print("BRAND: wrote %s (%dx%d)" % (path, img_w, img_h))


def make_splash(path, img_w=1000, img_h=500):
    buf = [0.0] * (img_w * img_h * 4)

    # Vertical gradient background, plus a soft radial lift behind the wordmark.
    cx, cy = img_w * 0.5, img_h * 0.56
    for y in range(img_h):
        t = y / (img_h - 1)
        base = [BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t for i in range(3)]
        for x in range(img_w):
            dx = (x - cx) / (img_w * 0.62)
            dy = (y - cy) / (img_h * 0.85)
            glow = max(0.0, 1.0 - (dx * dx + dy * dy)) ** 2 * 0.10
            off = (y * img_w + x) * 4
            buf[off] = base[0] + glow
            buf[off + 1] = base[1] + glow * 1.05
            buf[off + 2] = base[2] + glow * 1.15
            buf[off + 3] = 1.0

    scale = 34
    text_w, text_h = _text_extent("BLUI", scale)
    ox = (img_w - text_w) // 2
    oy = (img_h - text_h) // 2 - 8
    _blend_text(buf, img_w, img_h, "BLUI", scale, ox, oy, INK)

    # Accent rule under the wordmark, split so it reads as a progress mark.
    rule_y = oy - 26
    rule_x0 = ox
    rule_x1 = ox + text_w
    for y in range(rule_y, rule_y + 6):
        if y < 0 or y >= img_h:
            continue
        for x in range(rule_x0, rule_x1):
            off = (y * img_w + x) * 4
            lit = x < rule_x0 + int(text_w * 0.34)
            c = ACCENT if lit else (0.20, 0.24, 0.30)
            buf[off] = c[0]
            buf[off + 1] = c[1]
            buf[off + 2] = c[2]
            buf[off + 3] = 1.0

    _save(buf, img_w, img_h, path)


def make_logo(path, img_w=1024, img_h=256):
    """Transparent wordmark, used for the about/logo slots."""
    buf = [0.0] * (img_w * img_h * 4)

    scale = 24
    text_w, text_h = _text_extent("BLUI", scale)
    ox = (img_w - text_w) // 2
    oy = (img_h - text_h) // 2
    _blit_text(buf, img_w, img_h, "BLUI", scale, ox, oy, INK)

    _save(buf, img_w, img_h, path)


def main():
    outdir = _parse_args()
    os.makedirs(outdir, exist_ok=True)
    make_splash(os.path.join(outdir, "splash.png"))
    make_logo(os.path.join(outdir, "blender_logo.png"))
    print("BRAND: done")


main()
