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

### Only BLUI's editors exist

Blender registers eleven space types, and every one of them is reachable from
an area's *Editor Type* menu. BLUI's five 3D-editing editors are not part of
the product, so they are not registered, and the editor set is cut off at both
gates that matter:

* **The registry.** `ED_spacetypes_init()` no longer creates the 3D viewport,
  node editor, properties, outliner, clip editor, dope sheet, graph editor, NLA
  editor or spreadsheet space types. An unregistered space type cannot be
  opened, cannot be scripted, and is not offered by the operator search menu.
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
| Save isolation (edit a text file, save, read back) | `check_save_isolation.py` | PASS |
| Window / editor isolation (two Text windows) | `check_window_isolation.py` | ISOLATED |
| Opening a component in its own window | `check_component_window.py` | PASS |
| Click sweep, 144 points, whole window | `click_sweep.py` | no crash, no crash log |
| Configuration isolation | — | `%APPDATA%\Blender Foundation` untouched |

Two things are deliberately *not* covered, and are worth doing by hand:

* whether the tray icon is visible and its menu works after every window is
  closed - that needs a real click on the icon;
* whether a drag from the file browser lands in another application - the OLE
  loop cannot be driven by injected events.

### Known cosmetic issue

Starting BLUI prints ten lines of the form

```
RNA_boolean_set: OperatorProperties.extend not found.
Warning: property 'mode' not found in item 'OperatorProperties'
```

They come from the C keymap registration: `ED_spacetypes_keymap()` still calls
`ED_keymap_anim()`, `ED_keymap_object()`, `ED_keymap_mesh()` and friends, which
create keymaps for operators that BLUI no longer registers. They are harmless -
an operator property that is not found is skipped, and nothing is disabled by
it - but they will go away with the same strip that removes those `ED_keymap_*`
and `ED_operatortypes_*` calls.

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

      Second batch: **the editor set is now BLUI's own** (~4,600 lines across
      14 files, but nothing deleted yet). The ten Blender editors are no longer
      registered, no longer named in the space-type enum, and no longer
      referenced by the keymap data, the keymap tree, the UI modules or the
      `.blend`-facing defaults. Nothing is reachable from the Editor Type menu,
      from the operator search, or from Python. See *Only BLUI's editors exist*
      above, and `blui/tools/check_editor_set.py`.

      That is the reversible half. What remains is to **delete the now
      unreachable source**: `space_view3d`, `space_node`, `space_outliner`,
      `space_spreadsheet`, `space_clip`, `space_action`, `space_graph`,
      `space_nla`, `space_buttons`, `space_info`, `space_script`,
      `space_statusbar`, `space_topbar`, `object`, `mesh`, `sculpt_paint`,
      `uvedit`, `armature`, `metaball`, `lattice`, `curve`, `curves`,
      `physics`, `transform`, `gizmo_library`, `mask`, `animation` and their
      RNA, operator registration and UI scripts. Two things have to be checked
      first, and they are where the remaining work is:

      * **Operators the surviving components need but that are registered from
        a doomed module.** `transform_operatortypes()` was one (see the trap
        above). `ED_operatortypes_gpencil()`, `_paint()`, `_uvedit()`,
        `_marker()`, `_sound()`, `_render()` and `_asset()` are all still
        called from `ED_spacetypes_init()` and should be traced the same way
        before their modules go.
      * **The `ED_keymap_*` / `ED_operatortypes_*` calls themselves.** Cutting
        them is also what removes the ten lines of `OperatorProperties.* not
        found` noise described under *Known cosmetic issue*.

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

### Licensing

BLUI is derived from Blender and is distributed under the GNU GPL v2 or later.
The Blender Foundation copyright notice is preserved in source headers and in
the Windows resource block.
