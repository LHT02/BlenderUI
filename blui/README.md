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

## Compatibility: none required

**BLUI does not read or write Blender's `.blend` files, and does not need to.**
This is a deliberate product decision, not a limitation to be fixed later, and
it removes constraints that would otherwise shape the whole strip:

* **DNA structs can be deleted or changed freely.** `source/blender/make/dna`
  exists to describe Blender's data layout; BLUI's use of it is now internal
  only. Removing `SpaceView3D` or `SpaceNode` no longer has a file-format cost.
* **`BLENDER_VERSION` no longer has to stay pinned to 306.** It was pinned
  because the `.blend` reader, the DNA structs and the legacy `do_versions`
  upgrade paths all key off it.
* **The legacy upgrade machinery is dead weight.** Everything under
  `source/blender/blenloader/intern/versioning_*.c` exists to bring an *older
  Blender file* up to the current layout. BLUI only ever reads files it wrote
  itself, always at the current version, so every `MAIN_VERSION_ATLEAST` branch
  in them is unreachable.

`.blend` remains BLUI's own storage format for `startup.blend` and
`userpref.blend`, written and read by the same build. What is gone is any
obligation to understand anyone else's file, or an older one of its own.

The first deletion this unblocked is `blenloader/intern/versioning_cycles.c`
(61 KB): it migrated Cycles particle and shader data, every branch of it guarded
by a pre-2.80 version check, for a renderer BLUI does not contain.

---

## What makes this a separate product

### 1. A separate product version

`BLENDER_VERSION` is currently left at 306, Blender's file/DNA generation. It
used to be *pinned* there because the `.blend` reader, the DNA structs and the
legacy `do_versions` upgrade paths all key off it - but BLUI has no
compatibility obligation to anyone else's file (see *Compatibility: none
required* above), so that pin is now only a starting point rather than a
constraint.

BLUI has its own version in
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

### Only BLUI's editors exist

Blender registers eleven space types, and every one of them is reachable from
an area's *Editor Type* menu. BLUI's five 3D-editing editors are not part of
the product, so they are not registered, and the editor set is cut off at both
gates that matter:

* **The registry.** `ED_spacetypes_init()` no longer creates the 3D viewport,
  node editor, properties, outliner, clip editor, dope sheet, graph editor, NLA
  editor, spreadsheet or script space types. An unregistered space type cannot
  be opened, cannot be scripted, and is not offered by the operator search menu.
* **The enum.** `rna_enum_space_type_items` drives the Editor Type menu, the
  `SCREEN_OT_space_type_set_or_cycle` operator, `Area.type`, `Area.ui_type` and
  `Panel.bl_space_type` - it is the product's editor set, and it now names only
  the six components.

Info, Top Bar and Status Bar stay in that array so `Area.type` can still
identify them from Python, and `rna_Area_ui_type_itemf()` skips them, exactly
as it already skipped the two global areas. Three registrations are also kept
although they are not editors: `SPACE_SCRIPT` is a deprecated space id whose
only job is to carry the script operators, `SPACE_INFO` is what the `.blend`
reader falls back to for an area with no space data at all, and Top Bar /
Status Bar are the global areas BLUI does not create.

Everything that hard-coded `SPACE_VIEW3D` as "the default editor" now falls
back to the **file browser**, which is the component BLUI opens on:
`area_offscreen_init()` and `ED_area_init()`, `rna_Area_type_get()`, and the
two enum defaults in `rna_screen.c`. `screen_area_spacelink_add()` and
`ED_area_newspace()` also gained the NULL guard they were missing, so asking
for an editor BLUI does not have degrades to the file browser instead of
dereferencing NULL.

> **A trap worth knowing about.** `transform_operatortypes()` was called from
> `view3d_ops.c` - that is, it was registered as a side effect of the 3D
> viewport's space type callback. It is a *shared* facility, not a 3D one: the
> video sequencer's slide tool is the macro `TRANSFORM_OT_seq_slide`. Removing
> the 3D viewport would have silently taken the sequencer's slide operator with
> it. It now lives in `ED_spacetypes_init()`, which runs regardless of which
> space types exist. The same trap applies to any operator registered from a
> space type callback rather than directly.

The gesture modal keymaps in `wm_operators.c` no longer assign themselves to
operators from the removed spaces. `WM_modalkeymap_assign()` reports each
unknown operator by name, and it was reporting 22 of them on every start.

Python followed the same cut: `bl_ui._modules` imports only the component
editors, and the keymap tree (`bl_keymap_utils/keymap_hierarchy.py`), the
default and industry-compatible keymap data, and the theme panel generator were
trimmed to the same set. `space_type` is validated when a keymap, a panel or a
theme area is created, so these were raising `TypeError` at startup rather than
merely going unused - the editor set is not a cosmetic list.

Verified by `blui/tools/check_editor_set.py`, which checks the enum, the menu
operator, `Panel.bl_space_type` and the startup file together.

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
| `check_editor_set.py` | asserts only BLUI's editors exist, and that the startup file uses them |
| `check_preferences.py` | asserts the preferences sections and panels are BLUI's set |
| `check_keymap_config.py` | asserts the key configuration loads and still has Ctrl+S and Shift+F1..F6 |
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

Started: `wm.window_new` takes a `workspace` argument, so a component can be
opened in a window of its own rather than as a tab in someone else's. Reachable
from the BLUI app menu under *New Window ▸ Files / Images / Text / Video /
Settings / Console*, and it is what a system tray entry would call.
Verified: `wm.window_new(workspace="Settings")` produces a second window whose
workspace is `Settings` holding a `PREFERENCES` area, while `wm.window_new()`
with no argument still copies the current component.

Editor isolation: every new window now gets its **own layout**. Blender's
`wm.window_new` shares the source window's layout, a layout owns the screen, and
the screen owns the areas and their spaces — so two windows on one layout are
two views of the same editor. Two text editor windows shared a single
`SpaceText`, which meant opening a file in one changed what the other was
editing, and the image viewer had the same problem. `wm.window_new` now
duplicates the layout (and, when a component is named, duplicates that
workspace's layout for the new window).

Verified with `blui/tools/check_window_isolation.py`, which opens two Text
windows and compares them:

| | distinct screens | `SpaceText` shared |
| --- | --- | --- |
| before | 2 of 3 | yes |
| after | 3 of 3 | no |

Still shared: the datablocks themselves live in one `Main`, so the list of open
texts and images is common to all windows even though no two windows are looking
at the same one.

**Saving is per file, and isolated.** Saving in the image editor writes the
image, saving in the text editor writes the text file, and neither writes a
container that the other could clobber. Blender's `.blend` remains only as
BLUI's internal startup/preferences format, never as a user-facing document.

Implemented by `WM_OT_save_active_file` (`bl_operators/wm.py`), which is what
`Ctrl+S` and the File menu's *Save* now run. It looks at the focused component
and writes that component's file: `text.save` in the text editor, `image.save`
in the image editor, and a plain "this window has nothing of its own to save"
anywhere else. The File menu's document entries - New, Open, Open Recent,
Revert, Recover, Save As, Save Copy, Link, Append - and their `Ctrl+N`,
`Ctrl+O`, `Ctrl+Shift+O` and `Ctrl+Shift+S` shortcuts are gone with it.
Verified end to end: edit a text file in the text editor, press Save, and the
bytes on disk are the edited ones.

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

Wired up. `wm_ghost_init()` installs the icon, `ghost_event_proc()` turns a
`GHOST_kEventTrayCommand` into the matching action (`component:<name>` runs
`wm.window_new` with that workspace; `quit` quits), and the menu lists Files,
Images, Text, Video, Settings and Quit.

Closing the last window no longer quits while the tray is up: `wm_window_close`
keeps the process alive, which is what makes the tray worth having. Without a
window to copy, `wm.window_new` now builds a fresh one instead of failing, and
its poll accepts "no window but a tray is active".

Verified: builds, starts, and the existing checks still pass. **The
close-every-window-then-use-the-tray path is not covered by an automated test** -
it needs a real click on the tray icon - so that is worth exercising by hand.

## Verified state

Everything below is checked by a script in `blui/tools/`, not asserted from
memory. Run them after any change; none of them need a person watching.

| Check | Command | Result |
| --- | --- | --- |
| OLE drop source (`CF_HDROP` payload + COM contract) | `build\dragsource_selftest.exe` | PASS, 0 failures |
| Shell context menu (bind, populate, enumerate) | `build\shellmenu_selftest.exe` | PASS, 0 failures |
| Embedded startup workspace set | `verify_startup.py` | 6 workspaces: Console, Files, Images, Settings, Text, Video |
| Editor set (enum, menu operator, panels, startup file) | `check_editor_set.py` | PASS, 0 failures |
| Preferences panel set (sections, dropped sections, reworked panels) | `check_preferences.py` | PASS, 0 failures |
| Key configuration (loads fully, Ctrl+S, Shift+F1..F6) | `check_keymap_config.py` | PASS, 116 keymaps |
| Save isolation (edit a text file, save, read back) | `check_save_isolation.py` | PASS |
| Window / editor isolation (two Text windows) | `check_window_isolation.py` | EDITORS-ISOLATED, DOCUMENTS-SHARED |
| Open-document isolation (item 4's target) | `check_window_isolation.py -- --strict` | FAILS today, by design |
| Opening a component in its own window | `check_component_window.py` | PASS |
| Click sweep, 144 points, whole window | `click_sweep.py` | no crash, no crash log |
| Configuration isolation | — | `%APPDATA%\Blender Foundation` untouched |

Two things are deliberately *not* covered, and are worth doing by hand:

* whether the tray icon is visible and its menu works after every window is
  closed - that needs a real click on the icon;
* whether a drag from the file browser lands in another application - the OLE
  loop cannot be driven by injected events.

### Known cosmetic issue

Starting BLUI used to print ten lines of `OperatorProperties.* not found`.
**Eight of them are gone** - they came from `ED_operatormacros_node()`, which
built the node editor's macros out of steps naming node operators that are no
longer registered, so `RNA_boolean_set(mot->ptr, "socket_select", true)` ran on
a macro step that was never created. That call is removed and the lines with it.

Two remain, of the form

```
Warning: property 'mode' not found in item 'OperatorProperties'
```

They are the benign half of the same mechanism: `bl_keymap_utils/io.py` walks a
keymap item's properties and prints this instead of raising when a property is
absent, so the item is created without it and nothing is disabled. They are not
in `keymap_data/*.py` as `["mode", ...]`, so the item that carries them is
somewhere else - `keymap_hierarchy.py`, or a modal map built in C. Worth one more
look; not worth blocking on.

**The macro calls cannot be removed by deleting the registration alone.** That
was tried, and it made BLUI start with *no keymaps at all*: dropping the twelve
3D `ED_operatormacros_*` calls broke the whole key configuration load.
`bl_keymap_utils/io.py` walks a macro's nested properties with
`property_unset()`, which **raises** where the flat case only warns, so the
first keymap item naming a missing macro aborts the load -
`("TRANSFORM_OT_edge_slide", ...)` in the mesh keymap, from `mesh_ops.c:225`.
The operator registration and the keymap data that names it have to be removed
in the same step, and that is the shape of the remaining Stage 2 work.

`ED_operatormacros_action()` and `_graph()` came out safely, and `_node()` too -
the keymap data names no node operator outside a helper nothing calls. Each was
checked with `check_keymap_config.py` before believing the build. `_mesh()`,
`_uvedit()`, `_object()`, `_curve()`, `_armature()`, `_metaball()`, `_clip()`
and `_mask()` are still in, and each needs its keymap data removed with it.

Nothing in the suite noticed at the time, which is why `check_keymap_config.py`
now exists. It was verified against the failure on purpose: dropping
`ED_operatormacros_mesh()` alone takes the key configuration from 135 keymaps to
7, and the check reports 11 failures and exits 1. Restoring it returns 135
keymaps, PASS and exit 0.

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
- [~] **Stage 2 — Physical stripping.** Where it stands:

      | | Count |
      | --- | --- |
      | Editor modules deleted | 8 — `space_spreadsheet`, `space_nla`, `space_action`, `space_graph`, `space_script`, `lattice`, `metaball`, `space_buttons` (1,139 KB) |
      | Legacy versioning files deleted | 8 (~788 KB) |
      | `bl_ui` UI-script modules deleted | 53 (1.2 MB) |
      | `ED_operatormacros_*` calls | 16 → 3 (file, sequencer, gpencil - all kept components) |
      | `ED_operatortypes_*` calls | 26 → 15 (all kept components or blocked families) |
      | Operator bags removed whole | 11 |
      | Families removed from inside a bag | 8 |
      | Keymaps | 135 → 116 |
      | Startup warning lines | 10 → 2 |

      Everything still registered belongs to a component BLUI keeps, or is
      blocked by one - the rejections and the reason for each are in the tables
      below. There is no target left that has not been measured.

      First batch deleted (~1,600 files):
      - `intern/cycles` — the entire Cycles renderer
      - `source/blender/freestyle` — the Freestyle line-rendering engine
      - `source/blender/editors/io` + `source/blender/io/{alembic,collada,common,usd}`
        — the 3D import/export UI
      - `source/blender/blendthumb` — the `.blend` thumbnail handler

      Second batch: **the editor set is now BLUI's own** (~4,600 lines across
      14 files, but nothing deleted yet). The ten Blender editors are no longer
      registered, no longer named in the space-type enum, and no longer
      referenced by the keymap data, the keymap tree, the UI modules or the
      `.blend`-facing defaults. Nothing is reachable from the Editor Type menu,
      from the operator search, or from Python. See *Only BLUI's editors exist*
      above, and `blui/tools/check_editor_set.py`.

      Third batch: **the dead UI scripts are gone** — 53 files, ~1.2 MB, from
      `scripts/startup/bl_ui/`. These are the modules that draw Blender's 3D
      panels: `space_view3d`, `space_node`, `space_outliner`, `space_clip`,
      `space_graph`, `space_nla`, `space_dopesheet`, `space_properties`,
      `space_spreadsheet` and forty-odd `properties_*` modules. They were
      already unreachable — `bl_ui/__init__.py` stopped importing them when the
      editor set was cut — so this is pure removal, with no C-side coupling and
      no risk to the `.blend` format. The console output after the deletion is
      byte-for-byte what it was before.

      > Two of the "unused" modules were not unused, and one of them would have
      > been a real bug. `bl_ui/utils.py` holds the shared panel mixins and is
      > imported by name rather than listed in `_modules`, and
      > `bl_ui/space_time.py` looks like a dope-sheet module but
      > `space_sequencer.py:595` does `from bl_ui.space_time import
      > marker_menu_generic` - deleting it takes the sequencer's marker menu
      > with it, silently, because a missing menu is a runtime warning rather
      > than an error. Both are kept. Grep for the module name across the tree,
      > not just for its entry in the module list.

      That is the reversible half. What remains is to **delete the now
      unreachable C source**: the space types and the 3D data editors, with
      their RNA and operator registration -
      `space_view3d`, `space_node`, `space_outliner`, `space_spreadsheet`,
      `space_clip`, `space_action`, `space_graph`, `space_nla`, `space_buttons`,
      `space_info`, `space_script`, `space_statusbar`, `space_topbar`, `object`,
      `mesh`, `sculpt_paint`, `uvedit`, `armature`, `metaball`, `lattice`,
      `curve`, `curves`, `physics`, `transform`, `gizmo_library`, `mask` and
      `animation`. Two things have to be checked first, and they are where the
      remaining work is:

      * **Operators the surviving components need but that are registered from
        a doomed module.** `transform_operatortypes()` was one (see the trap
        above). `ED_operatortypes_gpencil()`, `_paint()`, `_uvedit()`,
        `_marker()`, `_sound()`, `_render()` and `_asset()` are all still
        called from `ED_spacetypes_init()` and should be traced the same way
        before their modules go.
      * **The `ED_keymap_*` / `ED_operatortypes_*` / `ED_operatormacros_*` calls
        themselves.** Cutting them is also what removes the ten lines of
        `OperatorProperties.* not found` noise described under *Known cosmetic
        issue* - but read that section first, because cutting the macro
        registrations before the keymap data that names them takes the entire
        key configuration down with it. Operator and keymap data go together.

      **Start with `space_spreadsheet`.** It is the smallest module and its
      coupling has been measured rather than estimated, so it is the one to
      prove the pattern on before repeating it 26 times:

      > **Done.** `space_spreadsheet` is deleted (24 files / 132 KB). What the
      > attempt taught is below, and the pattern is now known.

      ### Measure function leakage, not just types and headers

      The next target was chosen by counting, for each remaining module, how
      many *external* references its space-type enum and its DNA struct had, and
      how many of its headers other modules `#include`. On that basis
      `space_outliner` looked like the least coupled of the seven candidates -
      30 enum refs in 15 files, 20 struct refs in 8, and **zero** headers
      included from outside.

      It is not. Deleting it failed at once, because its **functions** leak far
      more widely than its types do: `ED_outliner_select_sync_from_{object,edit_bone,pose_bone,sequence,all}_tag()`
      is called from about fifty places in roughly fifteen files, and several of
      those files are in modules that *stay* - `space_sequencer`, `undo`,
      `windowmanager`, `makesrna`. `ED_outliner_give_base_under_cursor()` and
      `ED_outliner_collections_editor_poll()` are used by the interface
      eyedropper and by `object_edit.cc` respectively.

      So the three cheap counts are not enough. Before picking a module, also
      count how many times its **public functions** are called from outside it,
      and whether those callers survive. A module whose callers are all in other
      doomed modules is cheap; one whose callers are in `space_sequencer` or
      `windowmanager` is not, however small its enum surface looks.

      The outliner deletion was started and reverted. Reverting is
      `git checkout -- .` in `source/`, which restores deleted files as well as
      edits.

      ### Measure link symbols too, not just functions

      `space_buttons` (the Properties editor) was picked next on the corrected
      method, and it looked genuinely cheap: 7 public functions in
      `ED_buttons.h`, only 3 external calls, and exactly one of those in a
      module that stays (`screen/area.cc`).

      It still failed. The build got all the way to the link, and then wanted
      three symbols nothing declares in a header:

      ```
      bf_rna.lib(rna_ui_gen.c.obj)                : uiTemplateTextureUser
      bf_python.lib(bpy.c.obj)                    : buttons_context_dir
      bf_editor_interface.lib(interface_templates): uiTemplateTextureShow
      ```

      The Properties editor also exports **UI template callbacks** and a context
      directory - things reached through the RNA/template layer rather than
      through a header anyone greps for. Counting header functions cannot see
      them.

      So there are three counts to take before choosing a module, not two:
      the space-type enum and DNA struct references, the calls to functions in
      its **public header**, and the symbols its **object file** supplies that
      other targets link. The third one only shows up at link time, which means
      the cheap-looking module is not identified by reading - it is identified
      by trying, and reverting when the link fails.

      Both the outliner and space_buttons attempts were started and reverted.
      Two modules measured, two rejected, one deleted (`space_spreadsheet`, the
      one whose link surface turned out to be empty).

      ### The next module to try: `space_nla`

      Found by the try-and-revert method, and by a wide margin the cleanest
      candidate measured so far. Nine files, 217 KB, no public header, and its
      RNA touches only the DNA struct - so the scope reduction applies whole:
      keep `SPACE_NLA`, keep `SpaceNla`, keep the RNA, delete only the module.

      The build reaches the link and asks for exactly **six** symbols. Each has
      exactly **one** external user:

      | Symbol | Its only external user | Stays? |
      | --- | --- | --- |
      | `ANIM_nla_context_track_ptr` | `screen/screen_context.c` | yes |
      | `ANIM_nla_context_strip_ptr` | `screen/screen_context.c` | yes |
      | `ED_operatormacros_nla` | `space_api/spacetypes.c` | yes |
      | `ANIM_nla_context_strip` | `animation/fmodifier_ui.c` | no |
      | `nla_action_get_color` | `animation/anim_channels_defines.c` | no |
      | `ED_nla_postop_refresh` | `transform/transform_convert_nla.c` | no |

      Compare the two rejected modules: `space_outliner` leaked about fifty call
      sites across fifteen files, and `space_buttons` leaked three symbols that
      are reached through the RNA template layer rather than a header. This one
      is six single-line removals, three of them in files that survive.

      One caution for whoever does it: removing `ED_operatormacros_nla()` from
      `ED_spacemacros_init()` is the same shape as the change that once took the
      whole key configuration down (see *Known cosmetic issue*). The keymap data
      must not name an NLA macro. `check_keymap_config.py` is the guard - run it
      before believing the build.

      #### Modules rejected so far

      | Module | Why it is not cheap |
      | --- | --- |
      | `space_outliner` | ~50 `ED_outliner_select_sync_*` call sites in ~15 files, several that stay |
      | `space_buttons` | 3 link symbols reached via RNA/templates, not headers |
      | `space_clip` | 15+ symbols across mask, transform, screen, gpencil, RNA and Python - UI templates (`uiTemplateMovieClip`, `uiTemplateTrack`, `uiTemplateMarker`, `uiTemplateMovieclipInformation`), context dirs (`clip_context_dir`) and `ED_space_clip_get/set_clip/mask` |
      | `space_node` | 20+ symbols, and the decisive one is that **`bf_nodes` itself** needs `ED_init_standard_node_socket_type` and `ED_init_node_socket_type_virtual` - the node *system* depends on the node *editor*. Also `ED_node_clipboard_free` in `wm_init_exit.cc`, `ED_node_is_compositor` in `wm_draw.c`, and the whole `ED_node_tree_*` family in `rna_space.c` |
      | `space_nla` | **done - six single call sites** |

      Deleted so far: `space_spreadsheet` (132 KB, three attempts), `space_nla`
      (217 KB), `space_action` (220 KB, one line), `space_graph` (377 KB, four
      call sites). 947 KB of editor source.

      The pattern in the rejections is consistent: a module is cheap when
      nothing outside it calls in, and expensive when it exports **UI template
      callbacks**, **context directories** or **context members** - none of which
      live in a header, so none of which show up when reading. `space_buttons`
      and `space_clip` both fail that way.

      ### `space_node`'s coupling runs both ways - it cannot be unblocked in steps

      One direction was fixed: `bf_nodes` no longer calls
      `ED_init_standard_node_socket_type()` to install the node editor's draw
      callbacks (Blender's own comment: "XXX bad level call"). That edge is
      gone.

      The other direction cannot be removed on its own. Excising the
      `SpaceNodeEditor` RNA from `rna_space.c` - about 445 lines, and roughly ten
      of the twenty-plus unresolved symbols - fails at the link because
      `space_node.cc` calls `RNA_enum_node_tree_types_itemf_impl()`, which lives
      in the RNA block and calls `rna_SpaceNodeEditor_tree_type_poll()`.
      Restoring the one helper just moves the error to the next symbol.

      So the node RNA and the node editor module are mutually dependent and must
      be deleted **in the same step**, exactly like the data editors and
      `object`/`space_view3d`. `rna_Space_refine()` is the one thing in that
      neighbourhood that must be kept - it refines *every* space type's RNA, not
      just the node one, and removing it wholesale breaks all of them. Take only
      its `case SPACE_NODE`.


      `editors/metaball` is the smallest module in the tree (5 files, 35 KB) and
      was the obvious next try. It leaks seven symbols, and where they land is
      the point:

      | Symbol | Lands in |
      | --- | --- |
      | `ED_keymap_metaball` | `space_api/spacetypes.c` (stays) - one line |
      | `ED_mball_undosys_type` | `undo/undo_system_types.cc` (stays) - one line |
      | `ED_mball_editmball_free/make/load` | `object/object_edit.cc` |
      | `ED_mball_add_primitive` | `object/object_add.cc` |
      | `ED_mball_select_pick` | `space_view3d/view3d_select.cc` |

      Every data editor has this shape. `undo/undo_system_types.cc` registers one
      undosys line per data type - armature, curve, font, lattice, metaball,
      mesh, curves, image, sculpt, particle, paintcurve, text, memfile - and
      `object` and `space_view3d` carry the edit-mode and selection glue for all
      of them.

      So the data editors are **not** a sequence of cheap deletions. Either they
      go as one group with `object` and `space_view3d`, or `object` and
      `space_view3d` go first and take most of the glue with them. Both are large
      changes, and neither is a "try it and see" - which is exactly why the four
      that *were* cheap are worth having banked first.

      For whoever continues: bank the cheap ones (the remaining space types,
      tried against the linker one at a time), then treat `object` +
      `space_view3d` + the data editors as a single planned block rather than
      discovering the interlock seven times.

      ### Operator registration is entangled with the keymap layer

      Removing `ED_operatortypes_X()` on its own is the wrong change, and so is
      removing it together with `ED_keymap_X()`. Both were tried.

      Removing nine `ED_operatortypes_*()` calls - metaball, lattice, geometry,
      sculpt, sculpt_curves, physics, curve, curves, armature - builds and passes
      every check, and puts nine `WM_modalkeymap_assign: unknown operator` errors
      on the console (`SCULPT_OT_brush_stroke`, `_expand`, `_mesh_filter`, the
      four gesture ops, `CURVE_OT_pen`). An operator and its **modal keymap** are
      registered from different places: `ED_operatortypes_sculpt()` supplied
      `SCULPT_OT_brush_stroke`, `ED_keymap_paint()` is what assigns a modal map
      to it, and the two calls sit adjacent in `ED_spacetypes_init()` with
      nothing to say they are a pair.

      So the curve pair was removed together - `ED_operatortypes_curve()` and
      `ED_keymap_curve(keyconf)`. That fixes the errors: zero unknown operators.
      It also takes the console from **2** `OperatorProperties not found` lines
      to **50**, because the keymap *data* still carries the curve entries and
      `bl_keymap_utils/io.py` prints one line per property it cannot set.

      It is a **triple**, not a pair:

      ```
      ED_operatortypes_X()   +   ED_keymap_X(keyconf)   +   X's entries in keymap_data
      ```

      The third is the one that costs, and it is the same rule that governed the
      macros - an operator and the keymap data naming it go together. Both
      attempts were reverted: a change that trades two clean console lines for
      nine errors or forty-eight warnings makes the next real problem harder to
      find, and the checks cannot see any of it.

      Note the signature difference that cost a round: `ED_operatortypes_X()`
      takes no arguments, `ED_keymap_X()` takes `keyconf`. A pattern matching
      `\(\)` silently removes only half the pair.

      #### The question from the curve triple, answered

      Last round left this open: removing the curve triple gave 42
      `OperatorProperties not found` lines and only eight were accounted for by
      `km_curve`. A grep said only `km_curve` names a `curve.*` operator, so the
      rest looked unaccounted for.

      They are `font.*`. **`ED_operatortypes_curve()` registers the whole
      `FONT_OT_*` set as well as `CURVE_OT_*`** - Blender keeps 3D-text editing
      in `editors/curve/curve_ops.c`, so one call supplies two families of
      operators with nothing in its name to say so. `km_font` holds 46 `font.*`
      entries, and the warning property names were `style`, `mode` and `action`,
      which are `FONT_OT_style_set`, `_case_set` and friends.

      So the `curve.*` grep was not wrong, it was answering a narrower question
      than the one that mattered. The unit of removal is not "the module whose
      name is on the function" but "everything that function registers":

      ```
      ED_operatortypes_curve()  ->  CURVE_OT_*  and  FONT_OT_*
      ED_keymap_curve()         ->  the Curve and Font keymaps
      keymap data               ->  km_curve (21) and km_font (46)
      ```

      That makes it a quadruple, not a triple, and the extra member is invisible
      from the function's name. Expect the same elsewhere: `ED_operatortypes_X()`
      is a bag, not a label.

      #### The mesh bag is clean, but its keymap data points into a kept module

      `ED_operatortypes_mesh()` was checked the same way, and it is the tidiest
      bag so far: 149 `MESH_OT_*` and no calls into any other registrar. The
      keymap data is equally contained - `km_mesh` with 47 entries in
      `blender_default.py` and 19 in `industry_compatible_data.py`, plus the two
      C call sites (`ED_operatortypes_mesh()` and `ED_keymap_mesh()`).

      It does not follow that it can be removed. `_template_items_uv_select_mode`
      - a helper used by the **UV keymaps, which BLUI keeps** - expands to
      `mesh.select_mode` items, and carries a bare `("mesh.select_mode", ...)`
      entry described in its own comment as a "hack to prevent fall-through".
      Removing the mesh operators makes those unknown operators inside a
      component that stays.

      So this one is not a mechanical removal like the curve editor; it needs a
      product decision first: does BLUI's image editor have a UV mode with
      select-mode switching, or is that whole corner of the keymap data dead?

      The evidence, gathered rather than guessed: the embedded startup file's
      image area is in **`VIEW`** mode, which is what a viewer wants - but
      `space_image.py` still carries live UV branches (`elif tool_mode == 'UV'`,
      `if sima.mode != 'UV'`), so the mode is reachable through the editor's own
      controls. The keymap data is therefore not dead yet; it is dead only once
      the image editor stops offering a UV mode.

      That makes the order clear: retire UV mode from the image editor first -
      it is a viewer - and the mesh operators and the UV keymap data become
      removable together afterwards. Doing it the other way round would turn
      working keymaps into unknown operators inside a component BLUI keeps.

      Note the contrast with the curve case. There, the extra member of the bag
      was an invisible operator family (`FONT_OT_*`). Here the bag is clean and
      the surprise is in the *data*, reaching from a module being deleted into
      one being kept. Both directions have to be checked.

      ### Two more bag shapes, and a correction

      **A bag can delegate.** `ED_operatortypes_physics()` is seven lines and
      registers nothing directly:

      ```c
      operatortypes_particle();   operatortypes_boids();   operatortypes_fluid();
      operatortypes_pointcache(); operatortypes_dynamicpaint();
      ```

      Counting `WM_operatortype_append` inside it therefore finds an empty bag
      and reads as "nothing to remove", which is the opposite of the truth. The
      test has to follow the calls, not count them.

      **A bag can span families.** `ED_operatortypes_object()` registers 223
      operators across six prefixes - `OBJECT_OT_*` (190), `CONSTRAINT_OT_*`
      (14), `GPENCIL_OT_*` (6), `POSE_OT_*` (6), `COLLECTION_OT_*` (5) and
      `TRANSFORM_OT_*` (2). Note `POSE_OT_*` appears here *and* in
      `ED_operatortypes_armature()`, which has already been removed - the same
      split family as `curves`/`sculpt_curves`, and the reason those two had to
      go together.

      **A correction.** When this bag was first looked at, the two
      `TRANSFORM_OT_*` entries read as the sequencer's `TRANSFORM_OT_seq_slide`
      dependency and the conclusion was that `ED_operatortypes_object()` is
      load-bearing for a component BLUI keeps. It is not: they are
      `TRANSFORM_OT_vertex_warp` and `TRANSFORM_OT_vertex_random`. The
      sequencer's dependency is on `transform_operatortypes()`, which is
      registered from `ED_spacetypes_init()` and is unaffected. Worth writing
      down because the wrong version was believed for part of a round.

      ### The UV mode gate - measured

      Three bags are now blocked on the same thing, not two. `mesh` and `uvedit`
      were known; `sculpt` joins them, because `km_image_editor_tool_uv_sculpt_stroke`
      in `blender_default.py` names `sculpt.*` operators. So retiring UV mode
      from the image editor unblocks all three at once, which makes it the
      highest-value single piece of work left in this vein.

      Its size, measured rather than estimated: **22 references to `SI_MODE_UV`
      across 14 files**.

      | Where | Refs |
      | --- | --- |
      | `blenkernel/intern` | 8 |
      | `editors/space_image` | 7 |
      | `draw/overlay` | 3 |
      | `editors/uvedit` | 2 |
      | `makesdna` (the enum itself) | 1 |
      | `editors/transform` | 1 |

      The full list, so the next attempt does not have to re-derive it:

      ```
      makesdna/DNA_space_types.h:1297            SI_MODE_UV = 3   (the enum)
      makesrna/intern/rna_space.c:253            the "UV Editor" item
      blenkernel/intern/paint.cc:540,571,634
      blenloader/intern/versioning_defaults.cc:127
      draw/engines/overlay/overlay_edit_uv.cc:47,110
      draw/engines/overlay/overlay_grid.cc:46
      draw/intern/draw_view.c:215
      editors/space_image/image_edit.c:49,97,467
      editors/space_image/space_image.c:804,1018,1024,1025
      editors/transform/transform_snap.cc:942
      editors/uvedit/uvedit_buttons.c:244
      editors/uvedit/uvedit_select.c:5611
      windowmanager/intern/wm_keymap_utils.c:161
      windowmanager/intern/wm_toolsystem.c:432
      ```

      Four are `case SI_MODE_UV:` in switches and have to go with the enum
      (`paint.cc:634`, `draw_view.c:215`, `space_image.c:804`,
      `wm_keymap_utils.c:161`); the rest are `== SI_MODE_UV` tests that become
      dead once the mode cannot be set.

      One looks removable and is not: `versioning_defaults.cc:127` fires when a
      workspace named "UV Editing" is created, and `WM_OT_workspace_add` can
      still create one even though BLUI has no top bar. Checked rather than
      assumed, because it read like dead code.

      Plus 6 references to the UV-sculpt keymaps in `blender_default.py` and none
      in `industry_compatible_data.py`.

      Note what is *not* in that list: the keymap data itself is barely involved
      (6 references), and the work is mostly in `space_image` and the drawing
      overlay. That is a different shape from the bag removals - it is a
      feature retirement, not a registration cut - and it needs the enum, the
      mode selector, the overlay and the transform code changed together.

      ### The object bag cannot be taken family by family either

      `ED_operatortypes_object()` is 223 operators across six prefixes, so the
      obvious next move was to take one family at a time by editing the
      individual `WM_operatortype_append` lines inside it. Tried it on the
      smallest, `CONSTRAINT_OT_*` (14).

      It fails for a reason that has nothing to do with constraints. The
      operators are named by **`interface_templates.cc`** - `CONSTRAINT_OT_apply`,
      `_copy`, `_copy_to_selected`, `_move_to_index`, `_delete`, and a
      `WM_operatortype_find("CONSTRAINT_OT_move_to_index")` that would get NULL
      back. That file is the interface layer, and BLUI keeps it.

      It is the **template-layer trap** again, the same one that made
      `space_buttons` and `space_clip` expensive: an operator reached through a
      UI template rather than through a header or a keymap. The object bag's
      families are wired into the interface templates for constraints, and
      presumably for the rest.

      So the object bag is not a set of six removable families. It is one
      block, and it comes out with `interface_templates.cc`'s constraint
      template code or not at all.

      No keymap data is involved - there is no `constraint.*` entry in either
      keymap file - which is why the usual signals said nothing.

      ### `editors/space_script/` is deleted, keymap data included

      The script space was the last space type registered for machinery rather
      than for a user: a pre-2.5 view whose `script_main_region_draw()` body had
      been commented out since 2.5, kept - per the comment in `ED_spacetypes_init`
      - only to carry two operators. Deleted whole (11 KB: `space_script.c`,
      `script_ops.c`, `script_edit.c`, `script_intern.h`), together with the
      `SpaceScript` DNA struct, the `SCRIPT_SET_NULL` macro and the
      `SPACE_SCRIPT = 14` enumerator.

      It is the bag method again, and the keymap is the part that bites. The
      `Script` keymap function never existed in `keymap_data` - the space's own
      keymap was always empty, so the count is unchanged at 116 - but `km_screen`
      carried `("script.reload", {"type": 'F8', ...})`. Deleting the operator and
      leaving that binding is exactly the macro failure recorded earlier in this
      file: a keyconfig that aborts part way and leaves single-digit keymaps.
      The binding, `wm_keymap_utils.c`'s `STRPREFIX(opname, "SCRIPT_OT")` special
      case, and the top bar's "System > Reload Scripts" menu entry all went in
      the same step.

      One thing deliberately kept: `WindowManager.tag_script_reload()`. It is not
      the operator's private machinery - `bpy/utils/__init__.py` calls it from
      `register_module` / `unregister_module` - so it stays and only its comment
      changed. Likewise `bpy.ops.script.reload` is gone but nothing in `scripts/`
      called it except a documentation index and that one menu entry.

      `SPACE_SCRIPT = 14` was removed rather than reused. Every value in that
      enum is explicit, so 14 is now an unused slot and 15/16/18 keep their
      meaning without a renumbering pass.

      The next unreachable space deletion is `space_topbar` + `space_statusbar`
      (10 KB + 5 KB). Both are still registered as global areas even though no
      area in the startup file uses one - `check_editor_set.py` asserts the
      startup areas are all offered editors, and neither is offered. Measured so
      the next round does not have to: about 30 sites, and unlike `space_script`
      most of them are *semantic* rather than declarative. The semantic ones are
      `screen_ops.c` (6, including the area polls at 4114/4182/4314/4335/4399/5517),
      `screen/area.cc` (827, 3347), `screen/screen_edit.c` (1104) and
      `wm_event_system.cc` (6086, 6146); the declarative ones are shared with
      `space_script` - `readfile.cc`, `wm_draw.c`, `rna_space.c`, `rna_screen.c`,
      `interface_template_search_menu.cc`, `interface/resources.cc`,
      `blenkernel/context.cc`, `screen_user_menu.c`, `gpencil_utils.c`. Every
      `ELEM(area->spacetype, SPACE_TOPBAR, SPACE_STATUSBAR)` test becomes
      unconditionally true once both are gone, so each one needs a decision
      rather than a deletion. That is why `space_script` went first.

      ### The undo registry was the data editors' one shared edge

      `editors/lattice/` looked like a 40 KB module whose public header was down
      to a single function, `ED_lattice_undosys_type()`. That is the shape of the
      whole data-editor layer - `ED_curves.h` is down to two functions, one of
      them its undo type. `editors/undo/undo_system_types.cc` was registering
      thirteen undo types, ten of which belong to editors BLUI does not have:
      armature, curve, font, lattice, metaball, mesh, curves, sculpt, particle
      and paint-curve. None of them could ever be pushed, because none of those
      editors can be entered.

      Those ten rows are gone. `ED_undosys_type_init()` now registers three -
      image, text, and the memfile fallback that has to stay last.

      The registry was the only edge the whole layer shared, so removing it drops
      every data editor's consumer count by exactly one. It is not by itself
      enough to delete any of them, and that is the finding worth keeping: they
      are all riders on the same two modules. Measured after the cut:

      | Module | Size | Consumers left |
      | --- | --- | --- |
      | `lattice` | 40 KB | **deleted** - see below |
      | `metaball` | 35 KB | **deleted** - see below |

      (The other four - `armature` 583 KB, `mesh` 1334 KB, `curve` 486 KB,
      `curves` 84 KB - were not re-measured site by site. Do that before quoting
      a number for them; the two above are the ones actually counted.)

      Every remaining consumer is itself on the deletion list, so the order is
      forced and it is the reverse of the intuitive one: **`object` and
      `space_view3d` have to go first** - they are the top of this cone, not the
      bottom - and the data editors follow them for free, the same way uvedit
      follows `mesh` and `transform`. Roughly 2.5 MB rides on those two.

      Two details a later pass should not lose:

      - `BKE_UNDOSYS_TYPE_SCULPT`, `_PARTICLE` and `_PAINTCURVE` are now declared
        and defined but never assigned, because `sculpt_undo.cc` and
        `paint_curve_undo.cc` still compare against them. They are null at
        runtime and harmless; they go with `sculpt_paint`.
      - Each module still carries its now-uncalled `ED_*_undosys_type()`
        definition. That is dead code, but it belongs to the module that will
        take it away, so it was left in place rather than deleted piecemeal.

      ### `editors/lattice/` is deleted

      The first module to fall to the undo-registry cut, and the shape of the
      cut is the point: four call sites, all in `space_view3d/view3d_select.cc`,
      and five includes that had been dead for a while.

      The four sites were the lattice edit-mode pre-deselect
      (`ED_lattice_flags_set(obedit, 0)`, three times - lasso, box, circle) and
      the lattice branch of the edit-mode click dispatch
      (`ED_lattice_select_pick`). Both are unreachable: BLUI has no edit mode at
      all. Removing them leaves `do_lasso_select_lattice`, `do_lattice_box_select`
      and the circle handler in place but inert, which is deliberate - they are
      `space_view3d`'s code and die with it, not with this module.

      Five of the six `ED_lattice.h` includes were already dead and had been
      since `ED_operatortypes_lattice()` was removed: `space_api/spacetypes.c`,
      `object/object_edit.cc`, `makesrna/rna_object.c` and
      `makesrna/rna_lattice.c` all included the header without calling anything
      in it. Only `space_view3d/view3d_select.cc` was live. That is the same
      leftover pattern as the `ED_uvedit.h` include in `spacetypes.c`, and it is
      worth expecting: removing an operator bag takes the calls but leaves the
      include, because nothing warns about an unused include of a header whose
      symbols are all gone.

      `bf_editor_lattice` had an **empty `LIB`**, which is why this one was safe
      to unlink outright - unlike `bf_editor_uvedit`, which turned out to be a
      linker hub carrying `bf_editor_object` and `bf_editor_mesh` into the
      executable for other modules. Check the `LIB` list before removing a link.

      `ED_lattice.h` went with it (all five of its declarations were lattice
      edit-mode entry points plus the undo type). The `Lattice` **ID and its DNA
      stay**: that is a data type the depsgraph, modifiers and RNA still use, and
      it is not what this deletion was about.

      A note on the build, because it cost a cycle: the three pre-deselect blocks
      are textually identical, so they were cut with one `replace_all` edit - and
      that matched only two of them, because the circle-select copy is the only
      one with no blank line after the closing brace. The compiler named the
      survivor (`view3d_select.cc(4522)`), which is the cheapest possible way to
      find it, but a `replace_all` across differently-formatted copies of the
      same block is worth not trusting.

      ### `editors/metaball/` is deleted, and one "dead include" was not dead

      Five live sites: the metaball branch of the edit-mode click dispatch in
      `space_view3d`, plus `ED_mball_editmball_load` / `_free` in `object`'s
      edit-mode enter and exit and `ED_mball_editmball_make` on enter. All
      unreachable, and both `object_edit.cc` chains end in a fallthrough, so
      deleting the `OB_MBALL` branches is enough - metaball edit mode is now
      simply refused, which is what BLUI wants.

      `OBJECT_OT_metaball_add` could not be cut so cleanly, because
      `ED_mball_add_primitive` is the whole point of the operator. It now creates
      the metaball object and stops there, with a comment saying so. It is
      unreachable from any BLUI menu, so that is tidying rather than behaviour.

      **The lesson is the include.** `ED_mball.h` looked dead in
      `overlay_metaball.cc` and `space_view3d/view3d_select.cc` - neither called
      an `ED_mball_*` function - so both includes were removed, and the build
      then failed on `MBALLSEL_RADIUS`, `MBALLSEL_STIFF` and `MBALLSEL_ANY`. A
      header can be live through constants alone, and grepping for its function
      prefix says nothing about that.

      That is the uvedit under-count in a new disguise, and it generalises the
      rule: **when deciding whether an include is dead, read the header's whole
      contents, not its naming convention.** The `ED_uvedit_` grep missed 17 of
      33 call sites because the symbols were not prefixed; this one missed three
      call sites because the symbols were macros. Both times the compiler found
      it and the grep did not.

      The three flags are select-buffer id bits (`1u << 30`, `1u << 31`), not
      editor state - the editor layer was only where they sat, because the file
      was named after the data type rather than after what the constants mean.
      They moved to `DNA_meta_types.h`, which both remaining users already
      include and which already carries the `MB_*` metaball constants.

      ### `ED_spacetypes_init()`'s include list, and the trap a third time

      `space_api/spacetypes.c` is where the removed operator bags left their
      headers behind, and it had become the densest collection of them: 28 `ED_*`
      includes in a file that now registers nine space types, fifteen operator
      bags and ten keymaps. Eleven were dead - `ED_armature.h`, `ED_clip.h`,
      `ED_curve.h`, `ED_curves.h`, `ED_curves_sculpt.h`, `ED_geometry.h`,
      `ED_mask.h`, `ED_mesh.h`, `ED_node.h`, `ED_physics.h`, `ED_sculpt.h` - and
      are gone.

      `ED_gizmo_library.h` was **not** dead, and the way it hid is the point: its
      symbols are `ED_gizmotypes_button_2d`, `ED_gizmotypes_dial_3d` and so on. A
      grep for `ED_gizmo_` does not match `ED_gizmotypes_`. That is the third time
      this session that a naming convention has hidden live code - `ED_uvedit_`
      missed the unprefixed internals, `ED_mball_` missed the macros, `ED_gizmo_`
      missed the compounded prefix - and all three were caught by the compiler
      rather than by reading.

      The method that works here is not grepping harder. Delete the includes and
      let the build name what was live: it costs one build cycle and the answer is
      conclusive. Grep is good for finding *candidates* and has now been wrong
      about all three of these, in both directions.

      These includes create no link dependency, so removing them deletes no code.
      They matter for the next step: an include of a module's header is exactly
      what has to be gone before that module can be deleted, and a stale one is
      invisible until the build breaks on it. `ED_lattice.h` and `ED_mball.h` each
      had one of these sitting in this very file.

      ### Measured and rejected: `physics` and `curves`

      Both looked like the next cheap rider after `lattice` and `metaball`.
      Neither is, and the reasons differ - recorded so the next pass does not
      spend a round rediscovering them.

      **`physics` (304 KB).** Its two headers are clean: `ED_particle.h` and
      `ED_physics.h` contain only function declarations and no macros, so the
      `ED_mball.h` trap does not apply here. But the `PE_*` API is called from
      *kept* modules, not only doomed ones:

      | Consumer | Sites | Kept? |
      | --- | --- | --- |
      | `draw/intern/draw_cache_impl_particles.c` | 2 | kept |
      | `draw/engines/overlay/overlay_particle.cc` | 4 | kept |
      | `makesrna/intern/rna_sculpt_paint.c` | 4 | kept |
      | `makesrna/intern/rna_object.c` | 1 | kept |
      | `space_view3d` (5), `transform` (6), `object` (3), `space_buttons` (1) | 15 | doomed |

      The kept half is the particle-cache *draw* path plus the particle-edit RNA,
      so deleting `physics` needs a product decision - does BLUI display particle
      systems at all - rather than a mechanical cut. `ED_rigidbody_object_remove`
      is also called from three places in `object_add.cc`.

      **`curves` (84 KB).** The byte count misleads: `ED_curves.h` is 239 lines
      exporting a ~25-function C++ API in `blender::ed::curves` - selection,
      transverts, poll functions, the screen-space box/lasso/circle select
      helpers. It is the hair-curves editor that sculpt mode drives. Small
      module, large surface.

      The pattern worth keeping: **module size is not a proxy for deletion
      cost.** `lattice` was 40 KB and cost four call sites. `curves` is 84 KB and
      exposes an API that would take a round of its own. Measure the header, not
      the directory - which is the same lesson as the include sweeps, arrived at
      from the other direction.

      ### `editors/space_buttons/` is deleted, in four layers

      CORRECTION, one round later. The heading here used to claim this module was
      "fully scoped" - seven RNA callbacks plus one call in `screen/area.cc`.
      Cutting exactly those and nothing else took the build **red** with three
      unresolved symbols, every one of them referenced from a module BLUI keeps:

      | Symbol | Referenced from |
      | --- | --- |
      | `uiTemplateTextureShow` | `editors/interface/interface_templates.cc` |
      | `uiTemplateTextureUser` | `makesrna`, via the generated `rna_ui_gen.c` |
      | `buttons_context_dir` | `python/intern/bpy.c` |

      So `space_buttons` is not only the Properties editor. It also implements UI
      *templates* that the interface layer and the generated RNA call, and it
      registers a context directory that `bpy.c` names. Those are not
      Properties-editor features - they are shared template machinery that sits
      in this module because the module was named after the space it served
      rather than after what it provides. `uiTemplateTextureShow` /
      `uiTemplateTextureUser` are the image-user template for texture datablocks:
      a 3D feature BLUI has no use for, whose *callers* are in modules BLUI keeps.

      The first attempt cut only layer 1 and was reverted - the tree was put back
      at `c19fc60` rather than left red. The second cut all four and is green.

      1. the seven `rna_SpaceProperties_*` callbacks in `makesrna/rna_space.c`,
         the `ED_buttons_search_string_get()` call in `screen/area.cc`, and the
         two `ED_buttons_*` calls in the doomed outliner;
      2. the `uiTemplateTexture*` definitions and their entries in
         `UI_interface.h`;
      3. the `UILayout.template_texture_user` RNA definition in `rna_ui_api.c`
         that generates the wrapper in `rna_ui_gen.c`, plus its one call in
         `interface_templates.cc`;
      4. `buttons_context_dir` in `buttons_context.c` and its name in `bpy.c`.

      Layers 2-4 are the point: `space_buttons` was not only the Properties
      editor. It also owned UI *templates* that the interface layer and the
      generated RNA call, and a Python context directory. That is shared
      machinery which sat here because the module was named after the space it
      served rather than after what it provides. `uiTemplateTextureShow` /
      `uiTemplateTextureUser` are the image-user template for texture datablocks -
      a 3D feature BLUI has no use for, whose callers were in modules BLUI keeps.

      Layer 1 alone, for the record - necessary, but not sufficient:

      The Properties editor is unregistered, so it is unreachable - but unlike
      `lattice` and `metaball` it is not held in place by doomed code. Both
      blockers are in modules BLUI keeps:

      | Site | What | Count |
      | --- | --- | --- |
      | `makesrna/rna_space.c:1955-2110` | the `rna_SpaceProperties_*` callbacks | ~10 functions |
      | `makesrna/rna_space.c:5279-5330` | the `SpaceProperties` RNA struct block | 1 |
      | `makesrna/rna_space.c:560` | `case SPACE_BUTTONS` in `rna_Space_refine` | 1 |
      | `makesrna/rna_space.c:531` | `#include "ED_buttons.h"` | 1 |
      | `editors/screen/area.cc:762` | `ED_buttons_search_string_get(sbuts)` | 1 |
      | `space_outliner/outliner_select.cc:1196-1197` | `ED_buttons_should_sync_with_outliner` | doomed |

      `ED_buttons.h` is only 1,276 bytes and exports seven functions, so the raw
      surface is small. The cost is that five of the seven are RNA property
      callbacks, so deleting them means deleting `SpaceProperties` from the RNA
      surface - a product statement ("the Properties editor does not exist"), not
      a mechanical cut. Same shape as `physics`: the blocker is never the module,
      it is that something BLUI keeps still exposes it.

      The `area.cc:762` case is worth separating from the rest. It is a single
      call site in a kept module holding a 105 KB module in place, and the cheap
      fix is to make the area search hook tolerate a space that cannot exist,
      rather than to keep the module for it.

      ### `editors/uvedit/`: the kept-module calls are gone, 29 sites remain

      CORRECTED. This section used to say uvedit was "four calls short", on the
      strength of "16 calls from outside the module". That number counted only
      symbols prefixed `ED_uvedit_`. Most of what crosses this boundary is *not*
      prefixed: `uvedit_uv_select_test`, `uvedit_edge_select_test`,
      `uvedit_face_visible_test`, `uvedit_face_select_test`,
      `uv_nearest_hit_init_max`, `uv_find_nearest_vert` and
      `UVPackIsland_Params::isCancelled` are all defined in `editors/uvedit/`
      and all called from outside it.

      **Grepping the prefix under-counts by more than half - 16 against 33.**
      The authority is the linker, not the grep: dropping `bf_editor_uvedit`
      from `space_image`'s `LIB` produced 19 unresolved symbols, several of them
      ones the prefix grep had never matched.

      `bf_editor_uvedit` is also a **linker hub**. Its own `LIB` is just
      `bf_bmesh`, but removing it from `space_image` took `bf_editor_object` and
      `bf_editor_mesh` out of `BLUI.exe` with it, so
      `bf_editor_space_image.image_edit.c.obj` then failed on
      `ED_object_get_active_image` - a symbol with nothing to do with UVs.
      Those libraries reach the executable *through* uvedit today. The link line
      cannot be trimmed until the module itself dies.

      The full external surface, measured:

      | Consumer | Sites | Symbols |
      | --- | --- | --- |
      | `transform/` (4 files) | 10 | prefixed + internals |
      | `mesh/` (3 files) | 9 | 7 of them internals only |
      | `sculpt_paint/` (2 files) | 6 | prefixed + internals |
      | `draw/intern/mesh_extractors/extract_mesh.cc` | 3 | internals only |
      | `space_image/` (2 files) | 2 | prefixed - **removed this stage** |
      | `makesrna/` (2 files) | 2 | prefixed - **removed this stage** |
      | `geometry/intern/uv_pack.cc` | 1 | `isCancelled` - **fixed this stage** |

      What went, and what the four decisions turned out to be:

      - `ED_uvedit_buttons_register(art)` was an unconditional registration of
        the UV panel category into the image editor's sidebar. A viewer has no
        UV mode, so those panels were unreachable - simply deleted.
      - `ED_uvedit_minmax_multi` sat behind `ED_space_image_show_uvedit()`,
        which needs mesh edit mode. That is a predicate living in *kept*
        `space_image/image_edit.c`, so it stays; only the branch went.
      - `ED_uvedit_get_aspect` backed `Scene.uvedit_aspect(ob)`, an RNA
        *function*, not a property. Without mesh edit mode it returned `(1, 1)`
        unconditionally, so the function and its registration were deleted.
      - `ED_uvedit_selectmode_clean_multi` backed the update callback of
        `ToolSettings.uv_select_mode`. The property **stays** -
        `bl_ui/space_image.py` still drives it - so only the callback and its
        `PROP_CONTEXT_UPDATE` flag were removed. (The name says `Scene`, the
        sdna says `uv_selectmode`: it is a ToolSettings property.)
      - Four now-dead `ED_uvedit.h` includes went with them, including one in
        `space_api/spacetypes.c` left over from the `ED_operatortypes_uvedit`
        removal.

      **Layering violation #2 fixed.** `bool UVPackIsland_Params::isCancelled()`
      was defined in `editors/uvedit/uvedit_unwrap_ops.cc` and called from
      `geometry/intern/uv_pack.cc:1562` - a core library calling into an editor
      library. The three-line definition moved to `uv_pack.cc`, beside its only
      caller. The first such violation was nodes-system -> node-editor.

      Noted for whoever deletes the module: `ED_image_draw_cursor()` lives in
      `uvedit_draw.c` but is a generic 2D-cursor helper with nothing UV about
      it. Its only caller is space_clip, also doomed, so it can go with the
      module instead of moving.

      The remaining 29 sites are all in `transform`, `mesh`, `sculpt_paint` and
      `draw`'s mesh extractor - every one a 3D module. uvedit has no consumer
      that stays, so it is no longer a separate job: it is a rider on those
      deletions.

      ### What deleting a module actually involves

      | Symbol | Refs | Files |
      | --- | --- | --- |
      | `SPACE_SPREADSHEET` | 25 | 16 |
      | `SpaceSpreadsheet` | 53 | 17 |
      | `ED_spacetype_spreadsheet` | 2 | 2 |
      | `spreadsheet_operatortypes` | 3 | 3 |
      | `RNA_SpaceSpreadsheet` | 3 | 3 |

      (The "~146 places" this section used to quote was the general problem, not
      this module. Measure before believing a number.)

      The job, in order, with the line numbers an attempt at it established.
      **This is one atomic change**: there is no green intermediate state, so it
      has to be done in a single pass and cannot be committed half way.

      1. `ED_spacetype_spreadsheet()` is **already uncalled** - it went with the
         space-type registry in the first batch - and nothing outside
         `space_spreadsheet/` calls `spreadsheet_operatortypes()` or
         `spreadsheet_keymap()`. Deleting the implementation cannot disturb the
         editor set.
      2. Delete `source/blender/editors/space_spreadsheet/` (24 files,
         132 KB), `source/blender/editors/include/ED_spreadsheet.h`, the
         `add_subdirectory(space_spreadsheet)` line in
         `editors/CMakeLists.txt`, and the declaration in `ED_space_api.h`.
      3. `modifiers/intern/MOD_nodes.cc`: drop `#include "ED_spreadsheet.h"`
         (line 85) and the `SPACE_SPREADSHEET` branch of the viewer-path scan
         (lines 964-968).
      4. `makesrna/intern/rna_space.c`: drop `#include "ED_spreadsheet.h"`
         (line 25), `case SPACE_SPREADSHEET:` in the space-type RNA lookup
         (line 584), `rna_SpaceSpreadsheet_geometry_component_type_update`
         (3213) and `rna_SpaceSpreadsheet_attribute_domain_itemf` (3250), the
         whole RNA block from `rna_def_spreadsheet_column_id` (7878) to the end
         of `rna_def_space_spreadsheet` (~8205), and its call (8206).
      5. `DNA_space_types.h`: the `SpaceSpreadsheet` struct and its
         `SPREADSHEET_*` defines.
      6. Build, run the suite, commit.

      **Scope reduction found by attempting it:** leave `SPACE_SPREADSHEET` in
      the `eSpace_Type` enum and leave the theme colours alone. That keeps
      `resources.cc`, `screen_ops.c`, `bpy_rna_callback.c`,
      `DNA_userdef_types.h` and `rna_userdef.c` compiling untouched - five files
      out of the job - at the cost of one dead enum value and some unused theme
      data, both of which can go in a later sweep once the modules are gone.

      An attempt at the above was started and **reverted** rather than left half
      applied: the repo requires the build to stay green at every step, and this
      change has no green intermediate. Undo is `git checkout -- .` in
      `source/`, which restores the deleted files as well as the edits.


      > **Note for whoever continues this.** "Guarded by a `WITH_*` option"
      > does *not* mean "safe to delete". Several intern libraries build a
      > **stub** when their feature is off and the core links that stub
      > unconditionally — `opensubdiv` (`BKE_subdiv_*`), `libmv`
      > (`BKE_tracking_*` includes `libmv-capi.h`) and `iksolver` are all in
      > this category. Deleting one produces `C1083: cannot open include
      > file`. Check for unconditional `#include`s of a library's headers
      > before removing it.

- [x] **Stage 2b — Delete the legacy `.blend` versioning.** Unblocked by
      *Compatibility: none required*. Every function here brought an **older
      Blender file** up to the current layout, written as a series of
      `if (!MAIN_VERSION_ATLEAST(bmain, x, y))` blocks. **Done: 8 files,
      ~788 KB** — `versioning_cycles.c` first, then `versioning_legacy.c`,
      `250`, `260`, `270`, `280`, `290` and `300`, with their call sites in
      `readfile.cc` and their declarations in `readfile.h`.

      The method, for the C-side deletion still to come below: a guard is dead
      when the file version already satisfies it. BLUI's files are 306.14, so
      `!ATLEAST(300, y)` is dead and `!ATLEAST(400, y)` is **live**. That test
      is what caught `versioning_400.cc` before it was deleted by mistake.

      What went, largest first:

      | File | Bytes | Call site in `readfile.cc` |
      | --- | --- | --- |
      | `versioning_legacy.c` | 73,955 | `blo_do_versions_pre250` @3588 |
      | `versioning_250.c` | 77,817 | `blo_do_versions_250` @3591 |
      | `versioning_260.c` | 86,253 | `blo_do_versions_260` @3594 |
      | `versioning_270.c` | 59,478 | `blo_do_versions_270` @3597 |
      | `versioning_280.c` | 195,032 | `blo_do_versions_280` @3600 |
      | `versioning_290.cc` | 73,752 | `blo_do_versions_290` @3603 |
      | `versioning_300.cc` | 178,568 | `blo_do_versions_300` @3606 |
      | `versioning_common.cc` + `.h` | 14,551 | helpers for the above |

      Plus the six `do_versions_after_linking_{250,260,270,280,290,300}` calls
      at `readfile.cc:3637-3652`, and the matching declarations in `readfile.h`.

      **Keep**, and the first two are not legacy upgrades at all:
      `versioning_defaults.cc` (sets defaults, no version guards),
      `versioning_userdef.c` (`blo_do_versions_userdef` @3556 and
      `do_versions_userdef` @3984 still run, and it carries defaults for the
      current version), `versioning_dna.c` (`blo_do_versions_dna` @1014, a DNA
      sanity check), and `versioning_common.cc` + `.h`, whose helpers
      `versioning_defaults.cc` and `versioning_400.cc` both include.

      **`versioning_400.cc` must stay, and getting this wrong is easy.**
      The test is not "is it guarded" but "**does the guard evaluate true for
      BLUI's own file version**". BLUI writes 306.14 (`BLENDER_FILE_SUBVERSION`
      is 14), so a guard on 400 is *live* while a guard on 300 is dead. An
      earlier version of this table listed `versioning_400.cc` as deletable; it
      is the one file in the set that actually runs. Check each guard against
      306.14 before deleting anything here.

      Both of the things worth checking before a deletion like this were
      checked. No `do_versions_*` body in the deleted set had unguarded
      top-level work that BLUI's own files rely on - the guards cover the whole
      body in each case, and both the build and the runtime suite agree. And
      `versioning_common.cc` really is shared: `versioning_defaults.cc` and
      `versioning_400.cc` both include its header, so it stayed with them
      instead of being swept up with the files it was written alongside.

      > One file can have more than one entry point. `versioning_cycles.c` had
      > `blo_do_versions_cycles` **and** `do_versions_after_linking_cycles`,
      > called from two different functions, and removing only the first left a
      > `LNK2019`. Let the linker find the second one rather than grepping for
      > the file name.

      **Checked and deliberately kept**, so the analysis does not have to be
      redone:

      * `versioning_userdef.c` looks like more of the same but is not.
        `blo_do_versions_userdef()` opens with **unguarded** repairs -
        `if (userdef->menuthreshold1 == 0) { ... }`, `if (userdef->autokey_mode
        == 0)` and so on. Those run on every load, including BLUI's own files,
        and fix up zeroed defaults. This is the "unguarded top-level work" that
        the guard test cannot see; read the body, do not just count guards.
      * `versioning_defaults.cc` sets defaults for newly created data and has no
        version guards at all.
      * `versioning_dna.c` is a sanity check that the file's DNA matches the
        build's. Cheap, and still meaningful for BLUI's own files.

      **Checked and rejected as a target:** the `DNA_DEPRECATED_ALLOW` blocks
      in `makesdna/DNA_*.h`. They look like more compatibility dead weight, but
      they are read by *current* code - `action.c`, `camera.c`, `constraint.c`,
      `customdata.cc` and others reference deprecated fields directly - so
      removing them breaks the build rather than shrinking it. There are only
      48 markers across 22 headers in any case; it is not the win it looks like.

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
      - [x] *Windows 11 style shell context menu.* Hosting the real shell menu,
        so it carries the entries Explorer shows - including those installed by
        other programs, and the ones Windows 11 hides behind "Show more
        options" (`CMF_EXTENDEDVERBS`). `intern/ghost/intern/GHOST_ShellMenuWin32.cc`
        parses the paths, finds their common parent folder, binds an
        `IShellFolder`, gets an `IContextMenu` off it, lets the shell populate an
        `HMENU`, and forwards the chosen verb through `InvokeCommand`. Exposed as
        `GHOST_ShowShellContextMenu()`.
        Verified against the live shell: the menu comes back with 43 entries,
        among them 7-Zip, Bandizip, TortoiseSVN, 百度网盘, PowerToys PowerRename
        and 火绒安全.

        It is reached from the file browser's context menu, as a *"Windows Shell
        Menu..."* entry at the top rather than replacing the menu, so Blender's
        own navigation and view entries (back, forward, parent, refresh, sort)
        stay where they were. That also mirrors the two-level shape Windows 11
        itself uses, where "Show more options" leads to the full shell menu.
        Operator: `file.shell_context_menu` in `editors/space_file/file_ops.c`.
- [x] **Stage 5 — Preferences.** Redesign the preferences panel for BLUI's
      component set instead of Blender's 3D options.
      - [x] Section list trimmed from 14 tabs to 9. Blender's Viewport, Lights,
        Animation, Navigation and Experimental sections exist to tune a 3D
        authoring tool - viewport quality, studio lights, keyframe defaults,
        orbit and fly/walk navigation, and prototypes for work in progress -
        and none of them have anything to configure for a file browser, an image
        viewer or a text editor. They are removed from
        `rna_enum_preference_section_items`, and a panel whose context is not in
        that list is never drawn. Add-ons is kept on purpose: BLUI ships none of
        its own, but leaving the section in keeps the product extensible.
        Verified: the live enum reports `INTERFACE, THEMES, EDITING, INPUT,
        KEYMAP, SYSTEM, SAVE_LOAD, FILE_PATHS, ADDONS`.
      - [x] The "Cycles Render Devices" panel is no longer registered - BLUI has
        no Cycles, so it could only ever draw an empty box.
      - [x] The panels behind those removed sections are no longer *registered*
        either. Being undrawable is not the same as not existing: the Navigation
        (orbit, zoom, fly/walk), Lights (studio lights, matcaps) and Experimental
        panels were still in `classes`, and Blender warns about each one at
        startup. They are gone, not merely unreachable.
      - [x] *Editing* is down to its **Text Editor** panel. Objects, New Objects,
        Duplicate Data, 3D Cursor, Annotations, Weight Paint, Grease Pencil and
        Miscellaneous all configure 3D content creation, which BLUI does not do;
        their panel definitions are deleted, not just unregistered.
      - [x] *Save & Load*: "Blend Files" became **Saving** and keeps only what
        applies to a real file - the overwrite prompt and "Tabs as Spaces" for
        the text editor. Relative paths, file compression, "Load UI", the number
        of backup versions, the Open Recent list length and the `.blend` preview
        thumbnail all described Blender's container. **Auto Save** is gone with
        them: it existed to write a recovery `.blend`. The **File Browser**
        panel is untouched - that one is BLUI's own subject matter.
        Verified by `blui/tools/check_preferences.py`, which walks the registered
        panel classes and asserts the whole set: nine sections, nothing in the
        dropped ones, Editing holding exactly one panel.

- [ ] **Stage 6 — Isolate the open-document list.** Blender is one document:
      every window edits one `Main`, so `bpy.data.texts` and `bpy.data.images`
      are common to all of them. Two text editor windows are genuinely separate
      *editors* now - distinct screens, distinct `SpaceText` - but they share
      one list of open documents, so either window can see, and switch to, the
      file the other has open.

      This is measured, not assumed: `check_window_isolation.py` opens one text
      per window and reports that window A can see 2 open texts including
      window B's.

      - [ ] Target: a window's open-document list holds only its own documents.
        `check_window_isolation.py -- --strict` asserts exactly that and
        **fails today**, on purpose. The work has a test to flip rather than a
        description to interpret; until it is flipped the suite runs the
        non-strict mode, which reports the measurement and passes.
      - [ ] Not started. This is where Blender's architecture resists hardest:
        `Main` is reached through `G.main` and through the context nearly
        everywhere, so "one `Main` per window" is not a local change. A narrower
        first step worth weighing is to leave storage alone and give the text and
        image editors a per-window *view* of the datablock list, so the dropdown
        and the browse list are per window even though the storage is not.

### Licensing

BLUI is derived from Blender and is distributed under the GNU GPL v2 or later.
The Blender Foundation copyright notice is preserved in source headers and in
the Windows resource block.
