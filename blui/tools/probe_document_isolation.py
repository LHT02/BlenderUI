# SPDX-License-Identifier: GPL-2.0-or-later
"""Stage 6 baseline: what is per-window today, and what is not.

Blender is one document. Every window edits one `Main`, so `bpy.data.texts` and
`bpy.data.images` are common to all of them; two text editor windows are separate
*editors* (distinct screens, distinct `SpaceTextEditor`) but share one list of
open documents. Stage 6 is "make each window's open-document list hold only its
own documents", and `check_window_isolation.py -- --strict` is the assertion to
flip.

This is the instrument for the step before that. It measures, changes nothing,
and always exits 0. Three things it establishes that the shipped check does not:

1. **The Image Editor shares the Text Editor's fate.** `check_window_isolation.py`
   only creates `bpy.data.texts`, so images are a blind spot: a Stage 6 change
   that isolated texts and forgot images would pass it. Measured here: an image
   opened in one window is visible from the other, exactly like a text.

2. **`bpy.data.images` is not empty at startup** (`Render Result`, `Viewer Node`),
   where `bpy.data.texts` is. Any image-based assertion has to tolerate those.

3. **There is no per-window axis to ride on.** Every window has its own `Screen`,
   but this build has one `Scene` (1 at startup) and every window's
   `window.scene` points at it. `Screen` carries no `scene` property at all, and
   its only collection is `areas`. So a per-window document list is new state -
   Stage 6 cannot be written as "give each window its own existing container".

It also records that the RNA surface for the removed editors is still generated -
`SpaceView3D`, `SpaceNodeEditor`, `SpaceOutliner`, `SpaceProperties` and the rest
are all still in `bpy.types` even though BLUI registers no such editor.

Run::

    build\\bin\\BLUI.exe --factory-startup \\
        --python source\\blui\\tools\\probe_document_isolation.py

Output goes to stdout and, line for line, to
`%TEMP%\\blui_probe_document_isolation.log` - the shell's own redirection buffers
until the process exits, so a hung run would otherwise leave no evidence.

Note for anyone extending this: a timer callback that raises is dropped by
Blender and the process then sits there with its windows on screen forever, and a
timer that returns `None` is unregistered and the next step never runs. Both are
why this script wraps every probe and returns an interval between steps.
"""
import os
import sys
import tempfile
import traceback

import bpy

_state = {"step": 0, "shared_texts": None, "shared_images": None}

LOG = os.path.join(tempfile.gettempdir(), "blui_probe_document_isolation.log")
try:
    open(LOG, "w").close()
except OSError:
    LOG = None


def _line(fmt, *args):
    text = "PROBE: " + (fmt % args if args else fmt)
    print(text)
    if LOG:
        try:
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError:
            pass


def _safe(label, fn):
    """Run `fn()`, report and swallow any exception."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - this is the point of the helper
        _line("  %-46s -> %s: %s", label, type(exc).__name__, exc)
        return None


def _window_row(win):
    """One line describing everything per-window we can actually read."""
    bits = ["workspace=%r" % win.workspace.name]
    screen = win.screen
    bits.append("screen=%r(%d)" % (screen.name, screen.as_pointer()))
    scene = getattr(win, "scene", None)
    bits.append("win.scene=%s" % (("(%r)" % scene.name) if scene else "ABSENT"))
    bits.append("areas=%s" % [a.type for a in screen.areas])
    return " ".join(bits)


def _rna_surface(cls):
    """Pointer/collection properties of an RNA type, or the error."""
    props = cls.bl_rna.properties
    return "%s: %s" % (getattr(cls, "__name__", cls),
                       [p.identifier for p in props
                        if p.type in {"COLLECTION", "POINTER"}])


def _step():
    win = bpy.context.window
    step = _state["step"]
    _state["step"] += 1
    try:
        # The return value matters: a Blender timer that returns None is
        # *unregistered*, so the chain stops. Steps return an interval to be
        # called again; the last step exits the process itself.
        return _body(win, step)
    except Exception:  # noqa: BLE001
        _line("UNCAUGHT in step %d:", step)
        traceback.print_exc()
        _finish()
        return None


def _body(win, step):
    if step == 0:
        _line("=== A/B: starting state ===")
        wm = bpy.context.window_manager
        _line("windows at start: %d", len(wm.windows))
        _line("bpy.data counts: texts=%d images=%d screens=%d scenes=%d workspaces=%d",
              len(bpy.data.texts), len(bpy.data.images), len(bpy.data.screens),
              len(bpy.data.scenes), len(bpy.data.workspaces))
        for i, w in enumerate(wm.windows):
            _line("  [%d] %s", i, _safe("row", lambda w=w: _window_row(w)))
        with bpy.context.temp_override(window=win):
            bpy.ops.wm.window_new(workspace="Text")
        return 0.5

    if step == 1:
        with bpy.context.temp_override(window=win):
            bpy.ops.wm.window_new(workspace="Images")
        return 0.5

    if step == 2:
        wm = bpy.context.window_manager
        windows = list(wm.windows)
        _line("")
        _line("=== A: after opening two more windows ===")
        _line("windows: %d", len(windows))
        screens = []
        for i, w in enumerate(windows):
            _line("  [%d] %s", i, _safe("row", lambda w=w: _window_row(w)))
            screens.append(w.screen.as_pointer())
        _line("distinct screens = %d of %d  <-- per-window state that exists",
              len(set(screens)), len(screens))

        _line("")
        _line("=== A2: is there a per-window scene to hang documents off? ===")
        scenes = []
        for i, w in enumerate(windows):
            sc = getattr(w, "scene", None)
            _line("  window[%d].scene = %s", i,
                  ("%r(%d)" % (sc.name, sc.as_pointer())) if sc else "ABSENT")
            if sc:
                scenes.append(sc.as_pointer())
        _line("  distinct scenes = %d of %d  <-- if 1, there is no axis here",
              len(set(scenes)), len(scenes))
        _line("  bpy.types.Window has .scene: %s",
              "scene" in [p.identifier for p in bpy.types.Window.bl_rna.properties])
        _line("  bpy.types.Screen has .scene: %s",
              "scene" in [p.identifier for p in bpy.types.Screen.bl_rna.properties])

        text_win = next((w for w in windows
                         if any(a.type == "TEXT_EDITOR" for a in w.screen.areas)), None)
        image_win = next((w for w in windows
                          if any(a.type == "IMAGE_EDITOR" for a in w.screen.areas)), None)
        if text_win is None or image_win is None:
            _line("")
            _line("no TEXT_EDITOR window (%s) or no IMAGE_EDITOR window (%s)",
                  bool(text_win), bool(image_win))
            _finish()
            return None

        t_area = next(a for a in text_win.screen.areas if a.type == "TEXT_EDITOR")
        i_area = next(a for a in image_win.screen.areas if a.type == "IMAGE_EDITOR")

        ours_t = bpy.data.texts.new("probe_doc_text")
        ours_i = bpy.data.images.new("probe_doc_image", 8, 8)
        t_area.spaces.active.text = ours_t
        i_area.spaces.active.image = ours_i
        _line("")
        _line("opened %r in the text window and %r in the image window",
              ours_t.name, ours_i.name)

        _line("")
        _line("=== C: documents, measured from inside each window ===")
        seen_t = seen_i = None
        for label, w in (("text window", text_win), ("image window", image_win)):
            with bpy.context.temp_override(window=w):
                seen_t = sorted(t.name for t in bpy.data.texts)
                seen_i = sorted(im.name for im in bpy.data.images)
            _line("  from the %s: texts=%s", label, seen_t)
            _line("  from the %s: images=%s", label, seen_i)

        _state["shared_texts"] = ("probe_doc_text" in seen_t)
        _state["shared_images"] = ("probe_doc_image" in seen_i)
        _line("  -> the text opened in one window is visible to the other: %s",
              _state["shared_texts"])
        _line("  -> the image opened in one window is visible to the other: %s",
              _state["shared_images"])
        _line("  -> text and image behave the same way: %s",
              _state["shared_texts"] == _state["shared_images"])

        _line("")
        _line("=== D: RNA surfaces a per-window document list could attach to ===")
        _line("  bpy.types Space* classes present: %s",
              sorted(n for n in dir(bpy.types) if n.startswith("Space")))
        for name in ("Screen", "Window", "SpaceTextEditor", "SpaceImageEditor"):
            cls = getattr(bpy.types, name, None)
            if cls is None:
                _line("  bpy.types.%s: ABSENT", name)
            else:
                _line("  %s", _safe("rna", lambda c=cls: _rna_surface(c)))
        for name in ("SpaceTextEditor", "SpaceImageEditor"):
            cls = getattr(bpy.types, name, None)
            if cls is not None:
                _line("  %s document props: %s", name,
                      _safe("doc", lambda c=cls: [
                          (p.identifier, p.type) for p in c.bl_rna.properties
                          if p.identifier in {"text", "image"}]))

        # Clean up our two datablocks so the run leaves nothing behind.
        bpy.data.texts.remove(ours_t, do_unlink=True)
        bpy.data.images.remove(ours_i, do_unlink=True)
        _finish()
        return None

    _finish()
    return None


def _finish():
    _line("")
    _line("=== summary ===")
    _line("texts shared across windows:   %s", _state["shared_texts"])
    _line("images shared across windows:  %s", _state["shared_images"])
    if LOG:
        _line("log: %s", LOG)
    _line("this script only measures; it never fails")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


bpy.app.timers.register(_step, first_interval=2.5)
