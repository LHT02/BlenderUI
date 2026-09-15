# BLUI

**BLUI** is a standalone file-browsing, image-viewing and text-editing
environment built on the Blender 3.6 source tree.

It is *not* a Blender add-on, a Blender build with a different theme, or a
wrapper. It is a source-level fork: the UI framework (GHOST windowing, the
`wm` window manager, the DNA/RNA system, the `interface` widget toolkit) has
been taken and re-pointed at a different product identity, a different
configuration root, and a component set aimed at being a usable replacement
for the operating system's file explorer and image viewer.

```
D:\BlenderUI\
├── source\              Blender 3.6.23 fork (git branch `blui`)
│   └── blui\            BLUI's own files, so a clone is self-contained
│       ├── README.md    this file
│       ├── build.cmd    canonical configure + build driver
│       └── tools\       startup / brand-art generators and UI diagnostics
├── build\               out-of-source CMake/Ninja build (generated)
└── build.cmd            forwarder to source\blui\build.cmd
```

Paths below are relative to the project root, `D:\BlenderUI`.

---

## Quick start

```bat
build.cmd            :: configure (only if needed) and build
build.cmd configure  :: re-run CMake (keeps the cache), then build
build.cmd clean      :: delete the build directory
```

The same driver lives at `source\blui\build.cmd`; the copy at the project root
just forwards to it.

Requirements: Visual Studio 2022 with the C++ toolset, CMake >= 3.10, Ninja,
Git. The prebuilt dependency libraries live in `source\lib\windows_x64`
(a git submodule of the source repository, ~3 GB).

The build produces `build\bin\BLUI.exe`.

---

## What makes this a separate product

### 1. A separate product version

`BLENDER_VERSION` is *pinned* to the Blender file/DNA generation (306). The
`.blend` reader, the DNA structs and the legacy `do_versions` upgrade paths all
depend on it, so changing it would silently change file-format behaviour.

BLUI therefore has its own version in
`source/blender/blenkernel/BKE_blender_version.h`:

| Macro | Value | Meaning |
| --- | --- | --- |
| `BLUI_VERSION` | `100` | product version, `major * 100 + minor` |
| `BLUI_VERSION_PATCH` | `0` | patch level |
| `BLUI_VERSION_DIR` | `"1.0"` | directory name under the config root |
| `BLUI_PRODUCT_NAME` | `"BLUI"` | window titles, message boxes |

`BKE_blender_version_string()` now reports the **BLUI** version, so
`--version`, the splash screen and the status bar all read `1.0.0` rather than
`3.6.23`. The Blender version remains available internally for compatibility.

### 2. A separate configuration root

BLUI shares **nothing** with an installed Blender. This is enforced at the
lowest level, in the Windows path provider
(`intern/ghost/intern/GHOST_SystemPathsWin32.cc`):

| | Blender 3.6 | BLUI |
| --- | --- | --- |
| Per-user config | `%APPDATA%\Blender Foundation\Blender\3.6` | `%APPDATA%\BLUI\1.0` |
| Machine-wide config | `%PROGRAMDATA%\Blender Foundation\Blender\3.6` | `%PROGRAMDATA%\BLUI\1.0` |
| Cache | `%LOCALAPPDATA%\Blender Foundation\Blender\Cache` | `%LOCALAPPDATA%\BLUI\Cache` |

**Portable mode** is supported as well. If a `config` directory exists next to
`BLUI.exe`, all user files are written beside the executable instead, so BLUI
can live on removable media. This is Blender's own portable-install detection
(`BKE_appdir_app_is_portable_install`) reused for BLUI's identity — both layouts
are supported.

### 3. Separate environment variables

Every environment override was renamed, so exporting one for BLUI can never
affect a Blender installation (and vice versa):

| Blender | BLUI |
| --- | --- |
| `BLENDER_USER_CONFIG` | `BLUI_USER_CONFIG` |
| `BLENDER_USER_SCRIPTS` | `BLUI_USER_SCRIPTS` |
| `BLENDER_USER_DATAFILES` | `BLUI_USER_DATAFILES` |
| `BLENDER_USER_AUTOSAVE` | `BLUI_USER_AUTOSAVE` |
| `BLENDER_USER_RESOURCES` | `BLUI_USER_RESOURCES` |
| `BLENDER_SYSTEM_SCRIPTS` | `BLUI_SYSTEM_SCRIPTS` |
| `BLENDER_SYSTEM_DATAFILES` | `BLUI_SYSTEM_DATAFILES` |
| `BLENDER_SYSTEM_PYTHON` | `BLUI_SYSTEM_PYTHON` |
| `BLENDER_SYSTEM_RESOURCES` | `BLUI_SYSTEM_RESOURCES` |

### 4. A separate executable

The CMake target is still internally named `blender` (it is referenced by
hundreds of build rules), but the artifacts are renamed:

| Artifact | Name |
| --- | --- |
| main binary | `BLUI.exe` |
| launcher | `BLUI-launcher.exe` |
| CMake project | `BLUI` |
| Windows resource block | `BLUI`, `CompanyName "BLUI Project"` |

The launcher knows to start `BLUI.exe`, and the Windows file-association
helper registers `BLUI.exe` / `BLUI-launcher.exe`.

---

## The BLUI build profile

`source/build_files/cmake/config/blui.cmake` expresses "BLUI is not a 3D
suite" at build level. It disables the subsystems that only exist to model,
sculpt, simulate, render or exchange 3D data, and pins the subsystems the BLUI
components genuinely need.

**Disabled:** Cycles, Freestyle, OpenImageDenoise, Bullet, OpenSubdiv, OpenVDB,
NanoVDB, fluid/ocean/remesh modifiers, QuadriFlow, IK (Itasc + solver), libmv
motion tracking, Alembic, USD, MaterialX, OpenCollada, Draco, PLY/STL/OBJ/GPencil
import-export, Potrace, Haru, OpenXR, LLVM, the Blender thumbnailer, NDOF input.

**Kept:** the GHOST/window-manager/DNA/RNA shell, the editors, Python, FFmpeg,
AVI, sndfile, audaspace, OpenAL, OpenEXR, JPEG2000, Cineon, WebP, OpenColorIO,
internationalisation, IME input, freetype.

Disabling a subsystem here is the reversible first step of removing it: the
source still exists, it simply is not compiled. Once a configuration is proven
to build and run, the corresponding source tree can be deleted for real.

---

## The component shell

Out of the box Blender opens on `Layout`, a 3D viewport, next to ten other
workspaces about modelling, sculpting, shading and UV editing. A fork that
keeps that workspace set still reads as Blender no matter what the binary is
called, so BLUI ships its own.

`release/datafiles/startup.blend` is compiled into the executable
(`data_to_c_simple` in `source/blender/editors/datafiles/CMakeLists.txt`), so
replacing that file replaces the factory startup. BLUI's contains six
workspaces, each a single full-window area:

| Workspace | Editor | Purpose |
| --- | --- | --- |
| **Files** | File Browser | the explorer; this is the workspace BLUI opens on |
| **Images** | Image Editor | image viewing and inspection |
| **Text** | Text Editor | plain text editing |
| **Video** | Sequencer | video sequence editing |
| **Settings** | Preferences | configuration |
| **Console** | Python Console | scripting and diagnostics |

It is generated, not hand-edited:

```bat
build\bin\BLUI.exe --factory-startup --python source\blui\tools\build_blui_startup.py -- ^
    --output build\blui_startup.blend
```

That script has to run with a real window, because retyping an area and closing
areas go through operators that need a window/screen/area context. It is
written as a timer-driven state machine on purpose: `window.workspace = ...`
does not update `window.screen` inside a single script run, so each step has to
happen in its own pass through the event loop.

### No top bar, no status bar

Blender's top bar carries the workspace tabs plus the scene and view-layer
switchers; its status bar carries operator hints and scene statistics. Both
exist because Blender is one document that you switch modes within. A BLUI
component is a window of its own, so neither bar has anything to switch
between, and together they were the loudest remaining "this is Blender" cue.

`ED_screen_global_areas_refresh()` therefore creates no global areas for any
window - child and temporary windows never had them, BLUI applies that to
every window. Verified: every workspace's area reports `xy=(0,0)` and the full
window size, with no strip reserved at the top or bottom.

Two things lived in those bars and had to go somewhere:

* the **File / Edit / Window / Help menus**, which are now drawn by BLUI's own
  editor headers in `scripts/startup/bl_ui/space_blui.py`, one per component
  space type. This is where someone using a file browser looks for them anyway.
* the **reports banner** ("Cannot do that here"), which rides along in the same
  header so operator feedback is not lost.

Switching between components is now a window-level concern rather than a tab
strip, which is the direction the product is heading: separate windows for the
explorer, the image viewer and the text editor.

### Brand art

`release/datafiles/splash.png` and `blender_logo.png` are also compiled in, and
both were Blender's artwork. `source\blui\tools\make_brand_art.py` regenerates
them as a BLUI wordmark (a small bitmap font drawn straight into an image
buffer, so it needs no GPU and runs in `--background`):

```bat
build\bin\BLUI.exe --background --python source\blui\tools\make_brand_art.py -- --outdir build\brand
```

### UI diagnostics

`source\blui\tools\` also holds the scripts used to check that the shell
actually behaves. They are worth re-running after any change to the workspace
set:

| Script | Purpose |
| --- | --- |
| `verify_startup.py` | prints the workspace set and each area's active editor |
| `dump_screens.py` | dumps every workspace, screen, area and space |
| `click_sweep.py` | clicks a grid over the whole window |
| `interaction_test.py` | right-click, double-click and drag |
| `menu_click_test.py` | clicks along the topbar menu strip |
| `probe_workspace.py` | checks the area retype / close primitives |

The input-driving ones need `--enable-event-simulate`.

### Rebranding that is done and still to do

Done: window title, splash screen art, splash/about logo, the topbar app menu
label, the about dialog text and links, the status bar version, and the
default workspace set.

Still Blender: the `BLENDER` icon in the topbar is rendered from
`release/datafiles/blender_icons.svg`, so it still shows the Blender logo.
Changing it means editing that SVG and regenerating the icon sheet with
`release/datafiles/blender_icons_update.py`, which itself needs a working BLUI
binary to run.

## Product requirements

These are what BLUI is being built to be. They cut against Blender's original
design in specific ways, so they are written down here rather than inferred.

**Work on real files, not on a self-built document model.** BLUI is a file
browser, an image viewer and a text editor. It must reference files by their
ordinary OS paths and let other programs see the same files. Nothing should
live only inside BLUI's own container: no asset-library indirection, no
"libraries" that only BLUI can resolve, no importing a file into an internal
store before it can be used. If a user opens `D:\photos\a.png`, that file is
the document.

**Windows are independent of each other.** Blender is single-document: every
window edits the same `Main`, and `File ▸ Save` writes one `.blend` holding
everything. That is wrong for this product. Each window should stand on its
own — an image viewer showing a photo, a text editor on a file, a file browser
on a folder — and closing or saving one must not touch the others.

**Saving is per file, and isolated.** Saving in the image editor writes the
image, saving in the text editor writes the text file, and neither writes a
container that the other could clobber. Blender's `.blend` remains only as
BLUI's internal startup/preferences format, never as a user-facing document.

**No splash screen.** BLUI opens straight into the Files workspace. A splash
announces a product; here it is only something to dismiss. Implemented by
setting `USER_SPLASH_DISABLE` in `BKE_blendfile_userdef_from_defaults()`.

**No top bar and no status bar, and real windows instead.** Blender's top bar
existed to switch workspaces and scenes within one document, and its status bar
to report on that document. Neither fits a set of independent component
windows, and both read as Blender chrome. Switching components is a window-level
operation, not a tab strip.

**A system tray entry point.** Because BLUI is meant to sit alongside the
desktop shell, it should be reachable without a window being open: a tray icon
whose menu can open a specific component directly, Settings in particular.

## Roadmap

The work is staged so the build stays green at every step.

- [x] **Stage 0 — Foundation.** Fork Blender 3.6.23, separate the product
      version, configuration root, environment variables and executable name.
      Add the BLUI build profile.
- [x] **Stage 1 — Verify isolation.** BLUI builds and runs, writes
      `%APPDATA%\BLUI\1.0\config\userpref.blend`, and leaves
      `%APPDATA%\Blender Foundation` byte-for-byte untouched. The Windows
      binary reports `ProductName BLUI`, `FileVersion 1.0.0`,
      `OriginalFilename BLUI.exe`.
- [~] **Stage 2 — Physical stripping.** First batch deleted (~1,600 files):
      - `intern/cycles` — the entire Cycles renderer
      - `source/blender/freestyle` — the Freestyle line-rendering engine
      - `source/blender/editors/io` + `source/blender/io/{alembic,collada,common,usd}`
        — the 3D import/export UI
      - `source/blender/blendthumb` — the `.blend` thumbnail handler

      Remaining: the 3D editor modules (`space_view3d`, `object`, `mesh`,
      `sculpt_paint`, `uvedit`, `armature`, `metaball`, `lattice`, `curve`,
      `curves`, `physics`, `space_node`, `space_outliner`,
      `space_spreadsheet`, `space_clip`, `mask`, `transform`,
      `gizmo_library`), together with their RNA, operator registration and
      UI scripts. This is the large part of the job: even the smallest space
      type (`space_spreadsheet`) is referenced from ~146 places across DNA,
      RNA, the screen API, the search menu and the Python bridge, because
      removing a `SpaceType` means removing it from every registry that
      enumerates spaces.

      > **Note for whoever continues this.** "Guarded by a `WITH_*` option"
      > does *not* mean "safe to delete". Several intern libraries build a
      > **stub** when their feature is off and the core links that stub
      > unconditionally — `opensubdiv` (`BKE_subdiv_*`), `libmv`
      > (`BKE_tracking_*` includes `libmv-capi.h`) and `iksolver` are all in
      > this category. Deleting one produces `C1083: cannot open include
      > file`. Check for unconditional `#include`s of a library's headers
      > before removing it.
- [x] **Stage 3 — Component shell.** BLUI boots into its own workspace set
      (*Files*, *Images*, *Text*, *Video*, *Settings*, *Console*) instead of a
      3D viewport, with its own splash and logo art. See
      *The component shell* above.
- [~] **Stage 4 — Explorer.** Rework the file browser into a real file manager.
      - [x] *Drag out to other applications.* Blender 3.6 implements only the
        OLE **drop target** half (`intern/ghost/intern/GHOST_DropTargetWin32.cc`,
        `IDropTarget`): it can receive files dragged in from other programs but
        cannot hand files to them, so dragging a file out of the file browser
        did nothing. BLUI adds the other half —
        `intern/ghost/intern/GHOST_DragSourceWin32.cc`, an `IDataObject`
        carrying `CF_HDROP` plus the `IDropSource` that drives it — exposed as
        `GHOST_StartDragFiles()` and called from `ui_but_drag_start()` for
        `WM_DRAG_PATH` drags.
      - [ ] *Windows 11 style shell context menu* — the secondary "Show more
        options" menu.
- [ ] **Stage 5 — Preferences.** Redesign the preferences panel for BLUI's
      component set instead of Blender's 3D options.

### Licensing

BLUI is derived from Blender and is distributed under the GNU GPL v2 or later.
The Blender Foundation copyright notice is preserved in source headers and in
the Windows resource block.
