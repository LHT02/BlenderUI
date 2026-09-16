# BLUI

> ## Start here
>
> This document is long because it records what did *not* work as carefully as
> what did. If you are picking BLUI up, this is the short version.
>
> **Where it stands at `fe74c517a5e`:** build green, all seven checks in
> `blui/tools/` pass, and both native self tests pass
> (`shellmenu_selftest.exe`, `dragsource_selftest.exe`). Run them with
> `blui/tools/…` as described under *Verified state*; none need a person
> watching.
>
> **Open work, in the order it should be tackled:**
>
> 1. **Confirm the context menu by hand** - the one thing a script cannot do.
>    Right-click a file: "Windows Shell Menu..." should open the real shell
>    menu, 7-Zip's and TortoiseSVN's submenus should have entries, and the
>    "External" submenu should show either its entries or a disabled line
>    saying what to select. If the first two still do nothing, the fix in
>    `890db3b` (right-click selects the item under the cursor) is wrong and
>    that is what to chase - not the work below.
> 2. **Isolate the shell menu.** Opening it instantiates every installed shell
>    extension on the main thread, so a slow one freezes the UI and a hung one
>    freezes it for good. See *The shell menu is not isolated, and cannot be
>    moved as one piece* for the constraint that catches people out
>    (`TrackPopupMenu` must run on the window's own thread), the two halves that
>    can be split, and the three decisions to make first.
> 3. **Open-document isolation (objective item 4)** - give each window its own
>    document list. `check_window_isolation.py -- --strict` is the test to flip,
>    and `blui/tools/probe_document_isolation.py` measures what is and is not
>    per-window today.
> 4. **The remaining 3D editor modules (objective item 2).** Nine are gone
>    (1,144 KB). `object` and `space_view3d` are the top of the dependency cone
>    and must go first; roughly 2.5 MB of data editors follow them for free.
>    Everything measured is in the module tables below, including the ones
>    rejected and why.
>
> **Two habits this codebase rewards**, both learned the hard way and both
> recorded with their evidence:
>
> - **Do not trust a grep for symbols.** The compiler is the authority. Three
>   times a naming convention hid live code: `ED_uvedit_` missed unprefixed
>   internals (17 of 33 call sites), `ED_mball_` missed macros, `ED_gizmo_`
>   missed the compounded prefix. Delete the include or the call, build, and
>   read what the compiler names.
> - **Never leave the tree red.** Two attempts were reverted mid-round rather
>   than committed half-done; both are written up. A lost round is cheaper than
>   a broken fork.

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
| `check_keymap_config.py` | asserts all three presets load, keymap counts, Ctrl+S, Shift+F1..F6, and that no keymap names an unregistered operator |
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

> **It was broken, and this paragraph is why nobody knew.** The tray path did
> exist and did create a window, but it created an *invalid* one and BLUI died
> on the click. `wm_window_new()` only allocates; `wm_window_copy()` and
> `wm_add_default()` are what give a window its scene, view layer, workspace and
> layout. The tray path called `wm_window_new()` and then `WM_check()`, which
> brings up the GHOST window and runs the first draw - and set none of the four.
> With a sibling window present the other branch is taken and everything looks
> fine, which is exactly why the hand-test above was the only thing that could
> have caught it, and why it was worth writing down that it had not been run.
>
> `wm_window_new_exec()` now resolves the target workspace *first* and gives the
> fresh window all four, duplicating the workspace's layout so it does not share
> a screen. `wm_add_default()` is the reference for what a bare `wm_window_new()`
> needs: scene, view layer name, active workspace, active layout.

**Window titles name the content.** Blender titles a window after its `.blend`
file, which BLUI never has, so every window read "BLUI" regardless of what it
held and the `(Recovered)` marker could never appear. `wm_window_title()` now
describes the component: the directory in a file browser, the file path in the
text editor or image viewer, and a label for the sequencer, console and
preferences. The product name is deliberately **not** appended - the title bar
belongs to the window, and repeating the application name in all of them says
nothing about which window this is. With nothing specific to show it falls back
to the component's workspace name.

That is only half the job: a title has to be rewritten when the content changes,
or it goes stale the moment the user navigates. `wm_event_do_notifiers()` scans
the queue once per pass for the notifiers the components send when what they
display changes (`ND_SPACE_FILE_PARAMS`, `ND_SPACE_FILE_LIST`, `ND_SPACE_IMAGE`,
`ND_SPACE_TEXT`, `ND_SPACE_SEQUENCER`, `ND_SPACE_CONSOLE`, and
`ND_WORKSPACE_SET`) and rewrites every window's title if any of them is present.
The scan is deliberately **not** gated on `note->window == win`: several of
these are broadcast with a null window via `WM_main_add_notifier()`, so gating
on it would miss exactly the directory-change case it is there for.

### File browser operations

Four things the browser has to do that Blender's never did, because Blender's is
a file *dialog* and BLUI's is a file *manager*.

**Double-click opens the file.** Blender opens a file by handing it back to the
operator that asked for it, so with no such operator a double-click fell through
and was ignored. It now runs `ShellExecuteEx` `"open"` through
`BLI_windows_external_operation_execute()`, so file associations apply and
double-clicking a `.exe` launches it. Directories were already handled.

**Ctrl+C / Ctrl+X / Ctrl+V** work on files through the **system** clipboard, not
Blender's interface clipboard (`wm.copy`/`wm.paste` are for text and button
values), so a copy here pastes into Explorer and a copy there pastes here. The
payload is the same `CF_HDROP` the drag source already builds, which is why
`GHOST_DragSourceWin32_Clipboard*` lives next to it rather than in a new file.
Cut publishes the paths with `CFSTR_PREFERREDDROPEFFECT` set to move and touches
nothing - the files move when something pastes them. Paste never overwrites:
replacing a file is the user's decision and there is no prompt on this path, so
a name that already exists is skipped and reported.

Three details that are easy to get wrong and are written down for that reason:

- `SetClipboardData()` takes the handle on **success** and leaves it to the
  caller on failure, so freeing it afterwards is a double free. The self test in
  `blui/tools/dragsource_selftest.cc` round-trips the clipboard precisely
  because a mistake here is invisible in the UI.
- The operators are registered on **every** platform, not under `#ifdef WIN32`,
  and the keymap binds them unconditionally. The transport is Windows-only but
  fails closed, whereas a platform-dependent keymap is a *dangling binding* on
  the platform that lacks the operator - the exact failure the assertion in
  `check_keymap_config.py` exists to catch.
- Paste clears the clipboard after a move. Those paths no longer exist, so
  leaving them there would offer files that cannot be pasted again.

**The shell context menu** (`Windows Shell Menu...`) hosts `IContextMenu` for the
selected files. Two things it needed on Windows 10, which is what this fork is
developed on:

- `QueryContextMenu()` produces the top-level entries, but the messages that let
  an extension fill a submenu as it opens (`WM_INITMENUPOPUP`, `WM_DRAWITEM`,
  `WM_MEASUREITEM`, `WM_MENUCHAR`) go to a modal loop that `TrackPopupMenu()`
  owns. They are forwarded through a `WH_MSGFILTER` hook for the life of the
  popup; without it 7-Zip's and TortoiseSVN's submenus came up empty while the
  menu itself looked complete. `GHOST_ShellMenuWin32_SupportsMenuMessages()`
  exposes whether there is a receiver, and the self test asserts it - nothing
  else in the suite can see this half.
- `CMF_EXTENDEDVERBS` is passed only on Windows 11 and later. It exists to reach
  what Win11 hides behind "Show more options"; on Win10 there is no such split
  and passing it adds the verbs otherwise reserved for Shift+right-click.

The entry also only ever acted on **selected** files, and right-clicking does not
select in Blender's browser - selection is on left press. Right-clicking an
unselected file therefore collected nothing and cancelled, which is
indistinguishable from a dead menu entry. The invoke now makes the item under the
cursor the selection first, unless it is already part of it, so right-clicking
inside a multi-selection still acts on all of it.

`InvokeCommand` is tried by menu offset first and, if that is refused, again with
the canonical verb from `GetCommandString(GCS_VERBW)`. Some extensions populate
the menu and then fail to recognise their own command id, which is how an entry
ends up visible and inert.

#### The shell menu is not isolated, and cannot be moved as one piece

Opening the menu calls `QueryContextMenu`, which instantiates the COM object of
**every installed shell extension**. A slow one freezes the UI and a hung one
freezes it indefinitely, and this machine has seven or eight installed. That is
the problem the sibling Electron project solved, and the fix is not a straight
port, because of one constraint found while assessing it:

> **`TrackPopupMenu` must run on the thread that owns the window.** So
> `GHOST_ShellMenuWin32_Popup()` cannot simply be moved to a worker thread or a
> child process.

What can be split is the two halves:

| Phase | Where it can go | Why |
| --- | --- | --- |
| Build - `ShellMenu::build()`, i.e. bind, `GetUIObjectOf`, `QueryContextMenu` | worker thread or child process | this is where extensions are instantiated, so this is where the freeze is |
| Show - `TrackPopupMenu` and `InvokeCommand` | **main thread only** | modal loop, and it needs the owner window's thread |

Splitting them puts an `IContextMenu` created on one thread to use on another,
which is a COM apartment question that has to be settled deliberately rather
than by trying it. The sibling project sidestepped it entirely: it *enumerates*
the menu in a child process and renders the result in its own UI, invoking the
chosen verb back in the child. That avoids cross-apartment use, at the cost of a
menu that no longer looks native.

For BLUI the decisions to make first are therefore:
1. Worker thread (a hung extension leaks a thread but the UI survives) or child
   process (killable, which also survives a crash)?
2. Apartment model, if the object crosses threads.
3. Whether a menu that cannot be built within the timeout should fall back to
   BLUI's own context menu or open empty.

The measured numbers to design against are in the sibling project's `PROJECT.md`:
a per-request timeout, pending-request cleanup, and a **15-second cooldown after
a crash** so one bad provider cannot cause a spawn storm.

### Known gap: shortcut icons are not verified

`BLI_windows_file_icon_load()` asks the shell for the icon of what a `.lnk`
points at, and `filelist_file_create_entry()` turns it into a preview icon for
`.lnk` entries. It builds, and it fails closed - a failed load leaves the entry
with its ordinary icon - but **it has not been observed working**.

The reason is that there is no instrument for it yet, and three attempts to
build one have now been ruled out. Recorded so the next attempt does not repeat
them:

- The file list is **not reachable from Python**. `SpaceFile` exposes `params`
  and a handful of operators, not the entries, so `preview_icon_id` cannot be
  read from a script.
- Driving the browser to a folder **does not rebuild the list**. Setting
  `params.directory` updates the property - a later read shows the new path -
  but the entries stay those of the old directory. `file.refresh()` returns
  `{'FINISHED'}` and changes nothing, and `file.select_all()` returns
  `{'FINISHED'}` too.
- That last one is worth spelling out, because it looks like it should work:
  `select_all` *does* force entries to be created. Tracing
  `filelist_file_create_entry()` unconditionally shows the whole directory
  arriving, one line per entry - all of them from the directory the browser
  started in. So the load path runs and the `.lnk` branch is simply never
  reached, because no `.lnk` is ever in the list.

The right instrument is the one the shell menu already has: the GHOST SDK-only
pattern, which needs no window, no CMake and no file browser.
`shellmenu_selftest.cc` and `dragsource_selftest.cc` are the templates, and both
were written for exactly this reason - a native path that the UI cannot
exercise.

**That instrument now exists and the extraction is verified.**
`GHOST_ShellMenuWin32_LoadFileIconRgba()` does the work in the SDK-only C++
translation unit - where `IImageList` is usable as a COM interface, which it is
not from `winstuff.c` - and `shellmenu_selftest.cc` asserts it. On this machine
a `.lnk` comes back at **256x256** (the Jumbo tier, not the small system icon
`SHGFI_ICON` would have given), 27777 opaque and 31177 clear pixels of 65536:
something was drawn *and* the transparent surround survived, which is what
catches an uncleared DIB coming back as an opaque black square.

What is left is the wiring, not the risk: `filelist.cc` still calls
`BLI_windows_file_icon_load()`. Switching it to the verified GHOST call and
deleting the BLI copy is the next step, and it is mechanical.

### A sibling project worth reading

`C:\Users\LHT02\Documents\Codex\2026-06-27\electron-mui-explore-exe-tab-material`
is an Electron + MUI file explorer aimed at the same problem, and its
`PROJECT.md` is a running record of the same fights. Three things in it are
directly applicable:

- **Isolating the shell menu.** It moved the native shell-menu call out of
  `worker_threads` into a **separate child process**, with a per-request
  timeout, pending-request cleanup, and a **15-second cooldown after a crash**
  so a bad provider cannot cause a spawn storm. Its stated lesson is the
  important part: do not *block* cloud drives, network paths or virtual files to
  avoid crashes - isolate the third-party shell extensions, thumbnail providers
  and icon providers instead. A hung COM call cannot be killed in a thread, only
  in a process, which is what BLUI would need too.
- **Getting a real icon.** Its `GetSystemImageListBitmap()` uses
  `SHGetFileInfoW(SHGFI_SYSICONINDEX)` plus `SHGetImageList()` and
  `IImageList::GetIcon()`, walking Jumbo/ExtraLarge/Large/Small so the icon
  matches the requested size, and retrying with `SHGFI_USEFILEATTRIBUTES` when
  the path does not resolve. BLUI asks for `SHGFI_ICON | SHGFI_LARGEICON`, which
  is always the small system icon. Its conversion step is the same top-down
  32-bit DIB and `DrawIconEx()` BLUI uses, which is reassuring rather than
  instructive.

  > Attempted and reverted. `IImageList` is a COM interface and
  > `BLI_winstuff.c` is **C**, so it needs the `lpVtbl` form
  > (`list->lpVtbl->GetIcon(list, ...)`) rather than `list->GetIcon(...)`, and
  > the SDK's `IID_IImageList` is a value in C where the parameter wants a
  > pointer - the two compose differently in C and C++. Also note
  > `commctrl.h` / `commoncontrols.h` must come **after** `windows.h` or they
  > are a parse error, the same as `shellapi.h` earlier. The cheaper route is
  > to do the extraction in the new C++ file rather than in `winstuff.c`.
- **Never show an empty menu.** Its fix list includes "不选中文件时不再只显示空
  菜单" - the same symptom as BLUI's External menu, with the same conclusion.


## Verified state

Everything below is checked by a script in `blui/tools/`, not asserted from
memory. Run them after any change; none of them need a person watching.

| Check | Command | Result |
| --- | --- | --- |
| OLE drop source (`CF_HDROP` payload + COM contract + clipboard round trip) | `build\dragsource_selftest.exe` | PASS, 0 failures |
| Shell context menu (bind, populate, enumerate, file icons) | `build\shellmenu_selftest.exe` | PASS, 0 failures |
| Embedded startup workspace set | `verify_startup.py` | 6 workspaces: Console, Files, Images, Settings, Text, Video |
| Editor set (enum, menu operator, panels, startup file) | `check_editor_set.py` | PASS, 0 failures |
| Preferences panel set (sections, dropped sections, reworked panels) | `check_preferences.py` | PASS, 0 failures |
| Key configuration: all 3 presets load, Ctrl+S, Shift+F1..F6 | `check_keymap_config.py` | PASS on all three; **0 dangling bindings**, strict assertion armed |
| Unreachable `_template_*` helpers in the keymap data | `scan_dead_keymap_helpers.py --check` | PASS, 0 unreachable helpers (plain Python, no BLUI needed) |
| Save isolation (edit a text file, save, read back) | `check_save_isolation.py` | PASS |
| Window / editor isolation (two Text windows) | `check_window_isolation.py` | EDITORS-ISOLATED, DOCUMENTS-SHARED |
| Open-document isolation (item 4's target) | `check_window_isolation.py -- --strict` | FAILS today, by design |
| Opening a component in its own window | `check_component_window.py` | PASS |
| Opening a component with **no** window open, unknown components, repeated cycles | `check_window_new_without_window.py` | PASS, 16 assertions |
| Click sweep, 144 points, whole window | `click_sweep.py` | no crash, no crash log |
| Configuration isolation | — | `%APPDATA%\Blender Foundation` untouched |

The dangling-binding row is worth spelling out, because it was red for a while
and this table said so: the backlog was 34 bindings, then 16, then 7, and is now
**0** for all three presets. `MEASURED_DANGLING_BINDINGS` is the switch - while a
baseline is non-zero the scan prints a WARN, and at zero it asserts. It is 0, so
a dangling binding is a hard failure again rather than a note. Falsify-tested by
injecting one and watching it fail with exit 1.

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
`_uvedit()`, `_curve()`, `_armature()`, `_metaball()`, `_clip()` and `_mask()`
are still **called**; each needs its keymap data removed with it.

> **Corrected 2026-09-16.** An earlier revision of this paragraph listed
> `_object()` among the functions "still in". It is not: `spacetypes.c` calls
> only `_file()`, `_sequencer()` and `_gpencil()` now, so `_object()` was
> unregistered at some point. The paragraph was written from the comment in
> `spacetypes.c` rather than from the call list, and the comment is itself
> wrong - it claims "the four left - file, sequencer, paint, gpencil" while
> three calls are present. `ED_operatormacros_paint()` is defined, declared in
> `ED_paint.h`, and called from nowhere. Its absence is inert only because the
> one macro it registers (`PAINTCURVE_OT_add_point_slide`) appears in no keymap
> data - a coincidence, not a design. **Read the call list, not the comment.**
>
> The corresponding keymap-data entries for the unregistered macros were *not*
> removed at the same time, and they are dangling right now. See "Verification
> suite coverage boundaries" below.

Nothing in the suite noticed at the time, which is why `check_keymap_config.py`
now exists. It was verified against the failure on purpose: dropping
`ED_operatormacros_mesh()` alone collapses the key configuration to single-digit
keymaps, and the check reports failures and exits 1. Restoring it returns the
configuration to its normal size and a clean run.

**That verification is itself a cautionary note.** The 135 in the original write-up
was Blender's count, not BLUI's - this build measures 112 / 103 / 103. The
check "worked" because 7 keymaps is below any sane floor, so the test proved it
detects collapse, and said nothing about the number it was calibrated against.
See the corrections under blind spot 1 below.

## Verification suite coverage boundaries

A check is only worth its blind spot. This section records what each script in
`source\blui\tools\` actually looks at, so the next person does not read a green
run as broader coverage than it is. It exists because a real defect got through
the whole suite once already.

**Read this before trusting a PASS.** Most of these scripts assert one shape of
one thing. That is deliberate - each was written to catch one specific failure -
but it means "the suite is green" is a much weaker statement than it sounds.

| Script | Covers | Does **not** cover |
| --- | --- | --- |
| `check_editor_set.py` | the `Area.type` / `Panel.bl_space_type` enums, the editor menu, and the areas present in the **startup file** | a workspace created at runtime, or an area type reachable only through an operator |
| `check_preferences.py` | every registered `Panel` subclass with `bl_space_type == "PREFERENCES"`, grouped by `bl_context` | preferences that are not panels (operators, RNA properties, the `Input`/`Keymap` editors' contents) |
| `check_keymap_config.py` | all three shipped presets, their exact keymap counts, four required global keymaps, Ctrl+S, Shift+F1..F6, **and that every bound `idname` still resolves** | keymap items whose behaviour is wrong but whose operator exists; `Node Editor`-style editors with no keymap at all; whether a key bound to a *live* operator does anything useful |
| `check_window_isolation.py` | whether two windows share a screen, and whether the open-document list is per-window | editor types other than `TEXT_EDITOR` / `IMAGE_EDITOR`; anything about saving |
| `check_component_window.py` | that `wm.window_new(workspace=...)` opens the named workspace in a new window | what the new window *contains* beyond its workspace name; `--strict` isolation |
| `check_save_isolation.py` | Ctrl+S (via `wm.save_active_file`) writes the focused text editor's own file, read back from disk | the image editor's save path; a viewer with nothing to save; failure/cancel paths |
| `click_sweep.py` | that a grid of clicks over window 0 does not crash or assert | whether anything the clicks did was *correct*; popups beyond one Escape; multiple windows |

### Blind spot 1: only the active key configuration was checked

The original `check_keymap_config.py` read `keyconfigs.active` and stopped. The
annotation deletion removed `builtin.annotate` from
`keymap_data/blender_default.py` but left two references in
`keymap_data/industry_compatible_data.py` (one in `_template_items_basic_tools`,
shared by Object Mode and Grease Pencil Stroke Edit Mode, and one in the Image
keymap), producing three dangling `wm.tool_set_by_id` bindings. Every script
passed. It was inert rather than an abort - activating the preset still returned
`{'FINISHED'}` - but that was luck, not safety.

**Fixed 2026-09-16:** all three presets are now activated in turn and measured.
An important correction fell out of doing it:

**A preset being shipped is not the same as a preset being instantiated.** Only
`Blender.py` is loaded at startup; `Blender_27x` and `Industry_Compatible` are
created on demand the first time someone selects them in Preferences > Input.
At startup `keyconfigs` therefore holds exactly three entries - `Blender`,
`Blender addon`, `Blender user` - and the two on-demand presets are absent.
Touching `kc.preferences` does **not** materialize them (measured; it was the
first hypothesis and it is wrong). So the check tests whether the preset **file**
exists, then activates it **by filepath**, which is the path the UI itself uses.

Measured counts, 2026-09-16, `--factory-startup`:

| Preset | Keymaps |
| --- | --- |
| `Blender` | 112 |
| `Blender_27x` | 103 |
| `Industry_Compatible` | 103 |

Two corrections fell out of measuring this. The first is that the earlier value
quoted for a healthy configuration - 135, in the script's own comment - is
**Blender's** unmodified count and was never BLUI's; the floor of 100 was set from
a number this build cannot reach. The second is that a threshold alone is too
weak: a preset that silently lost 40 keymaps still passes it. The script now
asserts the exact counts above (`MEASURED_KEYMAP_COUNTS`) as well as the floor, so
a change is visible in either direction.

**Two invocation traps, both of which cost a round:**

- `--background` does **not** work. It builds the key configuration only part way:
  `keyconfigs` holds `Blender` (74 keymaps), `Blender addon` and `Blender user`,
  and `Blender_27x` / `Industry_Compatible` are not there at all. The script
  detects `bpy.app.background` and exits 0 with a SKIP line rather than reporting a
  false pass.
- Use `--factory-startup`. Without it the run picks up whatever user
  configuration is on disk and the counts will not match the table.
- `bpy.ops.preferences.keyconfig_activate()` takes **`filepath`**, not `file`.
  `file=` raises `keyword "file" unrecognized`, and because this runs inside a
  timer callback the process then dies of an access violation instead of printing
  a readable failure - the exit status the harness sees is a crash, not a result.
  `activate()` now wraps the call and `guarded_run()` catches anything that
  escapes, so a future mistake of this shape reports as an ordinary FAIL.

A preset whose script **raises** does not merely fail either: `bpy.utils.
keyconfig_set()` calls `execfile(filepath)` inside a bare `try/except` that only
stores the traceback for a `report` callback the operator never passes, so the
exception propagates straight out through the operator call. Measured:

    AttributeError: 'NoneType' object has no attribute 'loader'

from `bpy/utils/__init__.py:93`. That is why `activate()` catches rather than
trusts; a check that dies cannot report anything.

### Blind spot 2: "is what should be there present" without "does what is there still exist"

Counting keymaps cannot see a keymap item that names an operator which is no
longer registered, and that is exactly the residue a module deletion leaves.
The scan walks every `kmi.idname` in the configuration and asks the running
binary whether it resolves (`bpy.ops.<cat>.<name>.get_rna_type()`); reading the
keymap data files cannot answer it, because operators are registered from C.

**It is not a hypothetical.** Running it for the first time found **34 dangling
bindings** across the three presets - `Blender` 16, `Blender_27x` 13,
`Industry_Compatible` 5. This is *not* the annotation residue (that one was
fixed); it is a second, larger one, and the suite had never looked for it.

Every one was independently confirmed to raise `KeyError` on
`get_rna_type()`, against negative controls that resolve cleanly
(`object.gpencil_add`, `image.open`, `image.save`, `text.open`, `text.save`), so
the scan is not blanket-failing.

| Operator | Presets | Root cause |
| --- | --- | --- |
| `view2d.ndof` | `Blender`, `Blender_27x`, `Industry_Compatible` | `WITH_INPUT_NDOF` is **OFF** in `blui.cmake`, so `VIEW2D_OT_ndof` is not registered |
| `image.view_ndof` | `Blender`, `Blender_27x`, `Industry_Compatible` | same - `IMAGE_OT_view_ndof` is behind `#ifdef WITH_INPUT_NDOF` |
| `view3d.select` | `Blender` (Weight Paint **and** GP Stroke Weight Mode), `Industry_Compatible` (Weight Paint) | `space_view3d` deleted |
| `view3d.select_box` / `select_lasso` (×2) / `select_circle` | `Blender`, `Blender_27x` | `space_view3d` deleted |
| `view3d.object_mode_pie_or_toggle` | `Blender` | `space_view3d` deleted |
| `object.duplicate_move` | all 3 | `ED_operatormacros_object()` no longer called |
| `object.duplicate_move_linked` | `Blender`, `Blender_27x` | same |
| `collection.create` / `objects_remove` / `objects_remove_all` / `objects_add_active` / `objects_remove_active` | `Blender`, `Blender_27x` | `ED_operatormacros_collection()` no longer called |
| `text.uncomment` | `Industry_Compatible` | **not** a deleted operator - see below |

Three of these root causes were wrong in the first pass and are corrected here.
The corrections matter more than the table, because two of them change what the
fix should be:

**1. The `ndof` group is a build-configuration issue, not a deletion.** Both
`VIEW2D_OT_ndof` and `IMAGE_OT_view_ndof` still exist in the source
(`editors/interface/view2d_ops.cc:1517`, `editors/space_image/image_ops.c:793`)
and are still appended in their registration functions - but each append is
inside `#ifdef WITH_INPUT_NDOF`, and `build_files/cmake/config/blui.cmake:74` sets
`WITH_INPUT_NDOF OFF`. So the operators are absent from the binary while the
keymap data still names them. **Re-registering them is not the fix and neither is
touching the source**: BLUI has no use for a 3D space-navigator input path, so the
right move is deleting the keymap entries. What is worth noting is that this is
the only *nondeterministic-looking* group - if someone ever flips
`WITH_INPUT_NDOF` on, these bindings become valid again and the allowlist story
changes.

**2. `text.uncomment` is a keymap-only name; the operator is
`text.comment_toggle`.** There is no `TEXT_OT_uncomment` anywhere in the tree. The
real operator is `text.comment_toggle`, registered at
`editors/space_text/space_text.c:175`, with a `type` enum of
`TOGGLE` / `COMMENT` / `UNCOMMENT`. `blender_default.py:1407` binds the correct
name on Ctrl+/ ; `industry_compatible_data.py:794` binds the nonexistent
`text.uncomment` on Shift+Ctrl+D. This is inherited upstream breakage in Blender's
own preset, **not** something BLUI deleted - and it is the one finding that the
"a module deletion left this" narrative would have mis-attributed. The fix is a
one-line change to `text.comment_toggle` with
`{"properties": [("type", 'UNCOMMENT')]}`, which is what the original binding
plainly intended.

**3. `view3d.select` in the GP and weight-paint keymaps is not GP annotation
residue.** It is a "bone selection for combined weight paint + pose mode" binding
(`blender_default.py:2648`), guarded by `params.select_mouse == 'LEFTMOUSE'`. It
lives in `EMPTY`-space keymaps for paint modes, so it falls with `space_view3d`
rather than with anything GP-specific.

Where each group lives, and whether it is reachable at all:

| Keymap | Space type | Reachable in BLUI? |
| --- | --- | --- |
| `View2D` | `EMPTY` | **yes** - every 2D view uses it (file browser, image, text, sequencer) |
| `Image` | `IMAGE_EDITOR` | **yes** - Image Editor is a BLUI component |
| `Text` | `TEXT_EDITOR` | **yes** - Text Editor is a BLUI component |
| `Object Mode` | `EMPTY` | **yes** |
| `Object Non-modal` | `EMPTY` | **yes** |
| `Weight Paint` | `EMPTY` | only if a weight-paint-capable context exists without a 3D view |
| `Paint Vertex Selection (Weight, Vertex)` | `EMPTY` | same |
| `Grease Pencil Stroke Weight Mode` | `EMPTY` | same |

The space types matter because they are what makes a binding live. A dangling
binding in `View2D` or `Image` is on a real code path in a workspace BLUI ships; a
dangling binding in a paint-mode `EMPTY` keymap is not, because there is no 3D
view to enter paint mode from. Two of the 34 findings sit on genuinely live paths:

- `View2D -> view2d.ndof`, in the keymap every 2D view uses.
- `Image -> image.view_ndof`, in the Image Editor's own keymap.

Both are inert only because `WITH_INPUT_NDOF` is off - no ndof event is ever
generated, so nothing dispatches the item. They are still wrong entries in data
that ships, and they are the two that should be cleaned up first, because they are
the two that are one `cmake` flag away from being live.

The third live-path finding is `Text -> text.uncomment` in
`Industry_Compatible`, which is a stale name rather than a missing operator.

The `view3d.*` group is **expected and accepted**: BLUI has no 3D view, so those
bindings are unreachable by construction. The `object.*` and `collection.*`
groups are the interesting ones - they are live keymap entries for operators
whose registration was removed to stop an abort, and the keymap data was never
removed alongside. That is the same "registration and the data naming it must go
in one step" rule from the macro section above, applied to the *leftovers* of a
previous round rather than to a new deletion.

A related trap this run exposed: **a dangling binding is not necessarily a
`TypeError` waiting to happen, and its absence of symptoms is not evidence it is
fine.** All 34 are silent. All three presets still report 112/103/103 keymaps and
activate with `{'FINISHED'}`. `bl_keymap_utils/io.py` only *raises* when it has to
walk a dropped macro's nested properties with `property_unset()`; a plain
unregistered operator is stored as a name and never resolved at load time. So the
suite was blind in exactly the way that matters - the failure mode of a dangling
plain binding is a key that does nothing, which no count, no load check, and no
crash-detector can see.

The `DANGLING_ALLOWED` allowlist in the script is intentionally **empty**, so
the check can fail. It currently fails, which is the honest state: **groups 3
and 4 have not been cleaned up yet.**

**Update 2026-09-16: groups 1, 2 and 5 are fixed; 34 dangling bindings are down
to 16.** Measured with the same harness, so it is directly comparable:

| Preset | Before | After |
| --- | --- | --- |
| `Blender` | 16 | **7** |
| `Blender_27x` | 13 | **7** |
| `Industry_Compatible` | 5 | **2** |
| **Total** | **34** | **16** |

Keymap counts are unchanged at **112 / 103 / 103**, which is the check that the
deletions removed bindings and not keymaps. All seven scripts were re-run; see
`## Verification suite coverage boundaries` for the per-script results.

**Update 2026-09-16 (later round): 16 → 15, and only `Industry_Compatible`
moves.**

One group-5 binding had been missed. `Industry_Compatible -> Weight Paint ->
view3d.select` is in the original 34, but it was not on any of the three group
lists, so the group-5 sweep did not carry it. Its unreachability has the same
cause as the rest of group 5 - there is no 3D view to enter weight-paint mode
from - so it is pure cleanup and needed no product decision. It sat in the
`weights` list of `km_weight_paint` in `industry_compatible_data.py`, not inside
an `if` branch, so nothing was left empty behind it.

It only ever existed in `Industry_Compatible`: the same binding in `Blender`
(Weight Paint **and** GP Stroke Weight Mode) went with the group-5 sweep, and
`Blender_27x` never had one. A prediction of 6 / 6 / 1 made before the edit is
therefore wrong; the measured result is **7 / 7 / 1**. The first two numbers are
7 and should stay 7.

| Preset | Before | After |
| --- | --- | --- |
| `Blender` | 7 | **7** (unchanged - no such entry left) |
| `Blender_27x` | 7 | **7** (unchanged - never had one) |
| `Industry_Compatible` | 2 | **1** |
| **Total** | **16** | **15** |

What was changed, all in `keymap_data/*.py`:

- **Group 1** - deleted `view2d.ndof` and `image.view_ndof` from both preset
  files (four entries). The operators are genuinely absent from the binary, so
  there is nothing to bind.
- **Group 2** - renamed `text.uncomment` to `text.comment_toggle` with
  `{"properties": [("type", 'UNCOMMENT')]}`. The key intent was always correct;
  only the name was stale.
- **Group 5** - deleted the six unreachable `view3d.*` bindings and the two
  `if params.select_mouse == 'LEFTMOUSE':` blocks that existed solely to hold
  them. Two of those deletions emptied their block, so the block went too.

**One group-5 binding was re-pointed rather than deleted, and this is a
judgement call worth recording.** It is the only place in this cleanup where
"delete the dangling item" produced a wrong result, so it is worth knowing why:

`km_object_non_modal` has three branches. In the shipped default preset
`use_pie_click_drag` and `use_v3d_tab_menu` are both `False`, so the `else`
branch is the only one that ever runs - and it held exactly two items,
`object.mode_set` on Tab and the dangling `view3d.object_mode_pie_or_toggle` on
Ctrl+Tab. Deleting the dangling item would have left that branch with one item
and the `Object Non-modal` keymap with three, which is a visible behaviour
change to a keymap BLUI ships, not the removal of a dead binding. The slot was
instead re-pointed at `object.transfer_mode` (upstream already binds it in this
same keymap on Alt+Q; verified registered at `editors/object/object_ops.c:52`,
verified to resolve via `get_rna_type()`).

**This is a replacement, not a restoration, and it does not restore the old
behaviour.** `object.transfer_mode` copies the mode of the active object, so it
does nothing useful when the active editor is not an object context - in a text
editor or image editor Ctrl+Tab now has a binding that silently does nothing,
where before it had a binding that silently did nothing. Ctrl+Tab is a
3D-viewport gesture (`VIEW3D_MT_object_mode_pie`); with the 3D view gone there
is no faithful target for it. If a future reviewer would rather have the slot
removed and accept the one-item branch, that is a defensible alternative - it
was not taken here because shrinking a shipped keymap is the larger change.

The re-pointing checks cleanly: `object.transfer_mode` is now bound on both
`Alt+Q` and `Ctrl+Tab`, and the two do not collide as events.

One further correction, since this section previously implied otherwise:
`VIEW3D_MT_object_mode_pie` is **not** referenced anywhere in `bl_ui` (grep of
`source/scripts/`). Both remaining references are in
`keymap_data/blender_default.py` itself, and in the two branches that never
execute in the default preset. The mode pie is unreachable from the Python UI
regardless of this change.

The tempting shortcut is to park the `view3d.*` group in that allowlist - BLUI
has no 3D viewport, so those bindings are unreachable by construction. That is
the wrong move: the same allowlist would silence the `object.duplicate_move` and
`collection.*` bindings, which sit in **Object Mode** and are reachable in
workspaces BLUI ships. Those are real bugs. An allowlist populated to make a
suite green is how the suite stops being able to fail, which is the whole point
of this exercise. **The fix is to delete the keymap items, not to excuse
them.** A red run here is the signal working.

The immediate next step is to decide, per group, whether the binding or the
operator should go. Ordered by how live the code path is:

1. `View2D -> view2d.ndof`, `Image -> image.view_ndof` (**2 items, all 3 presets**)
   - live keymaps in components BLUI ships; inert only because
   `WITH_INPUT_NDOF OFF`. Delete the two keymap entries in
   `keymap_data/blender_default.py` (lines 836 and 1060) and the two in
   `keymap_data/industry_compatible_data.py` (lines 324 and 495). Cheapest fix,
   smallest blast radius. **Do these first** - they are the ones a cmake flag
   change would wake up.
2. `Text -> text.uncomment` (**1 item, `Industry_Compatible` only**) - change the
   name to `text.comment_toggle` and add
   `{"properties": [("type", 'UNCOMMENT')]}`. This is a correctness fix, not a
   deletion: the keybinding intent is fine, only the name is stale. Inherited from
   upstream, so it is also worth a one-line note that BLUI did not cause it.
3. `object.duplicate_move` / `duplicate_move_linked` (**3 items**) - bound to
   Shift+D / Alt+D in Object Mode and reachable. Either re-register
   `ED_operatormacros_object()` or remove the bindings. This is the one that needs
   a **product decision**, not a mechanical fix: bringing the macro family back
   re-opens the abort risk documented above. **Still open.**
4. `collection.*` (**9 items, but only 7 are dangling after dedup**) - bound to
   Ctrl+G and friends in Object Mode and reachable. Same choice as 3, same
   decision. **Still open.** Note `collection.objects_add_active` and
   `objects_remove_active` are counted per-preset, so the 9 name-occurrences in
   the table above are 7 distinct bindings in `Blender` and the same 7 in
   `Blender_27x` minus `collection.create`, which the 27x preset does not bind.
5. `view3d.*` (**7 items across `Blender`/`Blender_27x`) - unreachable: there is no
   3D viewport to enter paint or object mode from. Pure cleanup, no decision
   needed. **Done 2026-09-16.**

**Remaining after this round: 15, all of them groups 3 and 4.** They are the
same seven bindings in `Blender` and `Blender_27x`, plus one in
`Industry_Compatible`: `object.duplicate_move`, `object.duplicate_move_linked`
(not bound in `Industry_Compatible`), and the five `collection.*` entries. Every
one of them sits in the **`Object Mode`** keymap, which is a live keymap in
verifying BLUI workspaces - so unlike the group-5 entries these are real bugs,
and they are waiting on a decision rather than on effort.

**Full suite, re-run after this change** (real windows where they are required,
`--factory-startup` throughout):

| Script | Result |
| --- | --- |
| `check_editor_set.py` | PASS, 0 failures |
| `check_preferences.py` | PASS, 0 failures |
| `check_keymap_config.py` | `FAILED (3)` - the three intentional dangling assertions, nothing else |
| `check_window_isolation.py` | `RESULT_PASS` - EDITORS-ISOLATED, DOCUMENTS SHARED |
| `check_window_isolation.py -- --strict` | `RESULT_FAIL` - the Stage 6 assertion, red by design |
| `check_component_window.py` | PASS |
| `check_save_isolation.py` | PASS |
| `click_sweep.py` | 144 clicks, no crash, no crash log |

**The thresholds are exact for keymaps and as tight as they can be for bindings.**
`MEASURED_KEYMAP_COUNTS` asserts equality, so a preset that silently loses or
gains keymaps fails. `MEASURED_DANGLING_BINDINGS` asserts only "not worse than",
because the check has to stay red for the right reason (`has no dangling operator
bindings`) while groups 3 and 4 are open - but the recorded value is the number
the harness actually prints, so a regression in any cleaned-up group fails the
"not gained" assertion immediately. It has been tightened twice, 16/13/5 →
7/7/2 → **7 / 7 / 1**. Two things to keep straight when reading it:

- **7 / 7 / 1 is not 6 / 6 / 1.** The last group-5 leftover existed only in
  `Industry_Compatible`; `Blender` and `Blender_27x` had none left after the
  group-5 sweep. The first two numbers are 7 and should stay 7.
- An earlier revision of this paragraph read "`MEASURED_DANGLING_BINDINGS` is
  still 16/13/5 and is now loose by 9/6/3. Tighten it to **7 / 7 / 2**". That was
  the correct instruction for exactly one round; it has been carried out and is
  recorded here instead of being left to mislead the next reader.

When groups 3 and 4 are decided, tighten it to zero and the allowlist can stay
empty - the check then goes green on its own.

### Dead `_template_*` helpers in the keymap data

Looking for group 5 turned up a second kind of residue in the same two files.
Twelve `_template_*` helpers are **defined but called from nowhere** - 242 lines,
none of them reachable. Nine distinct names and twelve definitions, because
three names exist in both files and are live in one of them:

| File | Dead helpers (all deleted) | Lines |
| --- | --- | --- |
| `keymap_data/blender_default.py` | `_template_items_editmode_mesh_select_mode`, `_template_items_tool_select_actions`, `_template_items_uv_select_mode`, `_template_node_select`, `_template_uv_select`, `_template_view3d_select` | 152 |
| `keymap_data/industry_compatible_data.py` | `_template_items_editmode_mesh_select_mode`, `_template_items_object_subdivision_set`, `_template_items_tool_select`, `_template_items_tool_select_actions`, `_template_items_tool_select_actions_simple`, `_template_node_select` | 90 |

**Counting occurrences does not find them, in two different ways.**
`_template_items_object_subdivision_set`, `_template_items_tool_select` and
`_template_items_tool_select_actions_simple` appear twice in
`blender_default.py` - a definition and a call - so they are live there and dead
only in `industry_compatible_data.py`; a per-file "is this name referenced"
test reports the file, not the definition. And some dead helpers call each other
(`_template_items_tool_select_actions_simple` is reached only from its dead
siblings), so a single pass under-reports. The set only settles as a
**transitive closure** over the module's real entry points: 6 helpers in
`blender_default.py`, 6 in `industry_compatible_data.py` - 26 helpers defined and
20 live in the first file, 12 and 6 in the second. The scanner is now checked in
as `blui/tools/scan_dead_keymap_helpers.py` so the number is reproducible
(`--check` exits 1 if any dead helper reappears).

**They are deleted call sites, not unused code.** `git log -S` on each name shows
the callers went with BLUI's own module removals - the dangling-binding pattern,
one level up (the helper left behind while the keymap data naming it was
deleted):

| Helper | Call sites removed by |
| --- | --- |
| `_template_items_uv_select_mode`, `_template_uv_select`, `_template_items_tool_select*` | `05aa139e2a6` (remove the UV keymap data) |
| `_template_view3d_select`, `_template_node_select` | `88840345dec` (BLUI's editor set is the only one that exists) |
| `_template_items_editmode_mesh_select_mode` | `cd40af2c993` (remove the mesh bag) |
| `_template_items_object_subdivision_set` | `be71f35bd98` (remove the uvedit and sculpt bags) |

**Zero observable effect, and that is the point.** All seven scripts were re-run
after the deletion and report results **identical to the run before it**: dangling
7 / 7 / 1, keymap counts 112 / 103 / 103, `check_keymap_config` still
`FAILED (3)` and only on the three intentional assertions, `click_sweep` still 144
clicks with no crash log. A dead helper cannot move a count, so a green suite
proves the deletion was *safe* and proves nothing about whether it was *worth*
doing. It was worth doing because it is 242 lines a future reader would otherwise
have to reason about - `_template_view3d_select` in particular reads like a live
keymap builder and is what made this round start looking.


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
      | Editor modules deleted | 12 — `space_spreadsheet`, `space_nla`, `space_action`, `space_graph`, `space_script`, `lattice`, `metaball`, `space_buttons`, `space_statusbar`, `physics`, `space_topbar`, + their headers and registrations (1,461 KB) |
      | Legacy versioning files deleted | 8 (~788 KB) |
      | `bl_ui` UI-script modules deleted | 53 (1.2 MB) |
      | `ED_operatormacros_*` calls | 16 → 3 (file, sequencer, gpencil - all kept components) |
      | `ED_operatortypes_*` calls | 26 → 15 (all kept components or blocked families) |
      | Operator bags removed whole | 11 |
      | Families removed from inside a bag | 8 |
      | Keymaps | 135 → 116 |
      | Startup warning lines | 10 → 2 |

      **Target 4 (`object` + `space_view3d`, 2.3 MB) is measured and blocked.**
      See *`object` + `space_view3d` measured* below: both public headers are
      100% live (263 symbols, zero unreferenced), with 63 kept files depending on
      them - 7 of those in `makesrna/intern`, 18 in the kept `gpencil_legacy`
      annotation stack, and 7 in `windowmanager`. Nothing in targets 1-3 shrank
      that surface.

      **LHT answered the blocking question on 2026-09-16: annotation drawing is
      not kept.** That removes the largest kept consumer and turns the next step
      into `editors/gpencil_legacy/` (**1.6 MB, 35 files** - larger than either
      of them). It is scoped, not cut; the 63-entry keymap coupling and the
      object/annotation split are the work. See *The annotation question was
      answered* below. Until that lands, `object` + `space_view3d` remain in
      place, and the measurement above is still the reason.

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

      ### `editors/physics/` is deleted, and the "rejected" verdict was a product question, not a technical one

      CORRECTION. This section used to be titled *"Measured and rejected:
      `physics` and `curves`"*, and it put `physics` in the reject pile on the
      grounds that "the kept half is the particle-cache *draw* path plus the
      particle-edit RNA, so deleting `physics` needs a product decision rather
      than a mechanical cut."

      That diagnosis was right and the conclusion was wrong. The kept half was
      always severable - it was just work. LHT then made the product decision
      ("粒子系统、毛发曲线都不需要"), which is the thing the old text said was
      missing. So the reject pile held one genuinely-rejected module and one
      module that was merely *expensive*; the section conflated the two, and a
      future reader would have skipped a module that was ready to go.

      The measurement itself was accurate, and it is worth keeping in mind how
      accurate: the five file/line targets in the old table were **every one of
      them** a real call site. What the table understated was the *count* -
      `physics` exports 346 symbols, 27 of them declared in `editors/include`,
      and **42 have call sites outside the module**. The old table listed five
      files; the actual cut touched fourteen.

      | Symbol | External call sites |
      | --- | --- |
      | `ED_rigidbody_object_remove` | `object/object_add.cc:3032, 3148, 3380` |
      | `PE_current_changed` | `makesrna/rna_object.c:1266` (inside `#if 0`) |
      | `PE_get_current` | `makesrna/rna_sculpt_paint.c` (4), `transform/transform_convert.c:993`, `transform/transform_gizmo_3d.cc:845` |
      | `PE_create_current` | `draw/intern/draw_cache_impl_particles.c:1455`, `draw/engines/overlay/overlay_particle.cc:66` |
      | `PE_get_current_from_psys` | `overlay_particle.cc:78` |
      | `PE_settings` | `overlay_particle.cc:29,128` |
      | `PE_update_object` | `draw_cache_impl_particles.c:1433` |
      | `PE_start_edit` | `transform/transform_convert.c:993` |
      | `PE_minmax` | `space_view3d/view3d_navigate.cc:1286` |
      | `PE_mouse_particles`, `PE_box_select`, `PE_circle_select`, `PE_lasso_select` | `space_view3d/view3d_select.cc:3178, 4103, 5005, 1322` |
      | `ED_object_particle_edit_mode_supported/_exit_ex` | `object/object_modes.cc:118, 294` |
      | `PARTICLE_OT_particle_edit_toggle` (name) | `object/object_modes.cc:78` |
      | `rna_enum_particle_edit_hair_brush_items`, `..._disconnected_...` | `wm_toolsystem.c` (2), `bpy.c` via RNA |

      **What the old measurement got right and what it missed.** Everything in
      the table above was found by a reference scan (`refscan.py`, ~16 s over the
      whole `source/blender` corpus). What the scan *cannot* find - and what cost
      three build iterations - is the third category below.

      #### The three shapes the reference scan does not catch

      This is the reusable part. A scan for symbols catches call sites. It does
      not catch:

      1. **Definition-side coupling.** `draw/engines/overlay/overlay_edit_curves.cc`
         *calls* nothing from `physics` - it called
         `OVERLAY_shader_edit_particle_point()` / `..._strand()`, which are
         defined in `overlay_shader.cc`, a kept file. But those two wrappers were
         the *only* thing making the two GLSL files
         `overlay_edit_particle_{point,strand}_vert.glsl` exist, and the curves
         editor was **borrowing them**. Deleting the particle overlay pass took
         the curves editor's shaders with it. Fix: the two shaders were renamed
         to `overlay_edit_curves_{point,wire}_vert.glsl` and given proper
         `overlay_edit_curves_*` shader infos with the particle weight-brush
         branch (`useWeight`, `weight_to_rgb()`, `no_active_weight`) stripped out
         - that branch is a particle-hair brush feature and has no meaning in
         curves edit. **A shared shader is a hidden dependency: grep for the
         *file name*, not the symbol name.**
      2. **RNA enum arrays.** `rna_enum_particle_edit_hair_brush_items` and
         `rna_enum_particle_edit_disconnected_hair_brush_items` are `DEF_ENUM`
         declarations in `makesrna/RNA_enum_items.h` whose *storage* was in the
         deleted `rna_sculpt_paint.c`. They are named as strings from
         `wm_toolsystem.c` and `bpy.c`, so nothing in C looked unreachable, and
         the compiler could not tell me either - it was a **link** error
         (`LNK2001`), only visible at the final link of `BLUI.exe`, after
         `[642/642]` objects had compiled. Both use sites were dead anyway: each
         is guarded on `tref->mode == CTX_MODE_PARTICLE`, a mode that can no
         longer be entered.
      3. **A `nullptr` in a `.c` file.** One renamed update callback was left as
         `RNA_def_property_update(prop, NC_OBJECT | ND_DRAW, nullptr)` - correct
         in C++, a hard error in C (`error C2065: "nullptr": 未声明的标识符`).

      #### Other findings worth keeping

      - **`physics` was never wired into any registry.** A scan of all 79
        `PARTICLE_*` / `RIGIDBODY_*` / `BOID_*` / `FLUID_*` / `DPAINT_*` /
        `PTCACHE_OT_*` operator names found exactly **one** referenced outside the
        module: `PARTICLE_OT_particle_edit_toggle`, named as a string in
        `object_modes.cc:78`. `ED_operatortypes_physics()`,
        `ED_keymap_physics()` and `ED_particle_undosys_type()` have **no call
        sites at all** - not in `ED_spacetypes_init()`, not in `ed_undo.cc`.
        And there are **zero** keymap-data or Python references to any of them.
        So, contrary to what the old section implied, this deletion carried **no
        keymap-data step** - the macro/`property_unset()` trap that bit
        `space_script` and `space_statusbar` does not apply. That is the single
        biggest reason this module was cheaper than the reject pile implied.
      - **`OB_MODE_PARTICLE_EDIT` is an enum constant, not a symbol.** It is
        still referenced in fourteen places. Every one of them is a branch that
        can now never be taken, and none of them is a link error. They were cut
        where they guarded a *call* into `physics` (or would crash on a null
        second operand) and left where they are inert, in modules that are
        themselves doomed later in Stage 2: `space_view3d/*` (3),
        `object/object_modifier.cc` (4), `transform/*` (2),
        `outliner_draw.cc`, `interface_icons.cc`, `view3d_draw.cc`,
        `view3d_header.c`. Cleaning them up now would be churn against code that
        is about to be deleted anyway.
      - **`editors/undo/CMakeLists.txt` had `bf_editor_physics` in its `LIB`
        list** although `undo_system_types.cc` registers only `IMAGE`, `TEXT`,
        `MEMFILE`. It was already a stale link, so it was removed with the
        module.
      - **A duplicate function body survived a restore.** When
        `rna_Paint_brush_update` was restored after an over-broad cut (see the
        earlier session note), the restore landed *in addition to* the original
        rather than in place of it, giving two definitions
        (`error C2084: 函数...已有主体`). The file had the correct copy at line
        119 and a redundant copy at line 309. Worth remembering: after a
        "restore", grep for the symbol and assert the count is 1.

      #### Verification, all seven scripts, after the build went green

      | Check | Result |
      | --- | --- |
      | `check_editor_set.py` | PASS - 6 startup areas, all BLUI components |
      | `check_preferences.py` | PASS - all 10 kept sections, 5 dropped sections empty |
      | `check_keymap_config.py` | PASS - 116 keymaps, all 6 component hotkeys live |
      | `check_window_isolation.py` | PASS - `RESULT_PASS`, 3 windows, 3 distinct screens |
      | `check_component_window.py` | PASS - `RESULT_SETTINGS_WINDOW PASS` |
      | `check_save_isolation.py` | PASS - text editor wrote the real file on disk |
      | `click_sweep.py` | PASS - 144 clicks, no crash |

      `check_keymap_config.py` at **116 keymaps** is the meaningful number here:
      it is unchanged from before this deletion, which confirms the
      "no keymap coupling" measurement empirically rather than by grep.

      #### The reject pile, corrected

      `physics` (304 KB) is **deleted**. `curves` (84 KB) stays in the reject
      pile for now, on the grounds recorded below - and note that those grounds
      are now the *only* ones left in it.

      ### `curves` (84 KB) is still measured-and-rejected

      The byte count misleads: `ED_curves.h` is 239 lines exporting a ~25-function
      C++ API in `blender::ed::curves` - selection, transverts, poll functions,
      the screen-space box/lasso/circle select helpers. It is the hair-curves
      editor that sculpt mode drives. Small module, large surface.

      The pattern worth keeping: **module size is not a proxy for deletion
      cost.** `lattice` was 40 KB and cost four call sites. `curves` is 84 KB and
      exposes an API that would take a round of its own. Measure the header, not
      the directory - which is the same lesson as the include sweeps, arrived at
      from the other direction.

      Note the asymmetry with `physics`, because it is the actual lesson: both
      had a big exported API and neither was held by its *size*. `physics` fell
      because nothing registered it, so every reference was a call to be cut.
      `curves` is different - it is `ED_spacetypes_init`-visible work in the
      sculpt/paint path, and it will need the same three-shape sweep above
      (call sites, definition-side shared files, RNA/link symbols) before it can
      be judged. Do not assume it is rejected for the reason `physics` was;
      the reason `physics` was "rejected" turned out not to hold.

      ### `curves`, second measurement: 33 exported symbols, 9 callers, and a link graph that decides it

      Re-measured on 2026-09-16 with the three-shape sweep from the `physics`
      round. The verdict is **the same as physics, arrived at properly**: nothing
      registers `curves`, its reference surface is 9 files, and every one of
      those 9 is a call site that can be cut. The two are the same shape of
      module, and both were mis-filed.

      **Registry state - all three entries are dead, exactly as with physics:**

      | Registry entry | Call sites |
      | --- | --- |
      | `ED_operatortypes_curves()` | **none** - not in `space_api/spacetypes.c`'s 13 `ED_operatortypes_*` calls |
      | `ED_keymap_curves()` | **none** - not in `spacetypes.c`'s 10 `ED_keymap_*` calls |
      | `ED_curves_undosys_type()` | **none** - `undo_system_types.cc` registers only `IMAGE`, `TEXT`, `MEMFILE` |
      | any `CURVES_OT_*` name in keymap data or `bl_ui` | **none** - swept all of `presets/keyconfig/keymap_data/` and `startup/bl_ui/` |

      So the 28 `WM_operatortype_append()` calls in `curves_ops.cc` append into
      a list nobody reads, and the `"Curves"` keymap such as it is has no
      `poll` reachable. **No keymap-data step.** The `property_unset()` trap does
      not apply - third module in a row where the trap was assumed and measured
      absent.

      **The reference surface - 33 exported symbols, 9 consuming files:**

      | Consumer | Symbols | Kept? |
      | --- | --- | --- |
      | `makesrna/intern/rna_curves.c` | `ED_curves_offsets_for_write` (4), `ED_curves_point_normals_array_create` | kept |
      | `editors/util/ed_transverts.c` | `ED_curves_transverts_create` | kept |
      | `editors/object/object_add.cc` | `primitive_random_sphere`, `ensure_surface_deformation_node_exists` | **doomed** (Stage 2 target 4) |
      | `editors/space_view3d/view3d_select.cc` | `select_lasso`, `select_box`, `select_circle`, `closest_elem_find_screen_space`, `has_anything_selected`, `ensure_selection_attribute`, `fill_selection_false`, `apply_selection_operation_at_index` | **doomed** (target 4) |
      | `editors/transform/transform_convert_curves.cc` | `retrieve_selected_points`, `has_anything_selected` | **doomed** (target 4) |
      | `editors/transform/transform_gizmo_3d.cc` | `retrieve_selected_points` | **doomed** (target 4) |
      | `editors/sculpt_paint/curves_sculpt_ops.cc` | `curves_poll`, `curves_with_surface_poll`, `editable_curves_poll`, `get_unique_editable_curves`, `has_anything_selected`, `retrieve_selected_points`, `select_random` (namespace only) | **doomed** (target 4) |
      | `editors/sculpt_paint/curves_sculpt_{add,density,selection_paint,comb,delete,grow_shrink,pinch,puff,slide,smooth,snake_hook}.cc` | `retrieve_selected_curves`, `fill_selection_true/false` | **doomed** (target 4) |
      | `editors/include/ED_curves.h` itself | the header is the only remaining "caller" of 12 symbols | - |

      Six of the nine are modules already scheduled for deletion. The three that
      are genuinely kept are `makesrna/rna_curves.c`, `editors/util/ed_transverts.c`
      and `space_view3d` - and the first two are small.

      **Why this is still not a one-round job: the reachability question is a
      product question, and it is now sharper than for `physics`.** `curves`
      exists to serve *hair-curve sculpting* - it is the edit mode for `OB_CURVES`
      objects, driven by `sculpt_paint/curves_sculpt_*.cc` brush code. BLUI has
      no 3D viewport (`startup/bl_ui/space_view3d.py` is deleted) and no
      workspace that can host one, so `OB_CURVES` cannot be created *from the UI*.
      But unlike particles, `OB_CURVES` datablocks still exist in `DNA_object_types.h`
      and `object_add.cc` can still construct one programmatically.

      So the cuts split cleanly into two groups, and the split is the thing to
      decide:

      1. **`ED_keymap_curves`, `ED_curves_undosys_type`, and the 12 operator
         registrations** - unreachable by measurement, safe to cut whenever.
      2. **The ~25-function `blender::ed::curves` API** - reachable from kept
         modules only because `space_view3d` and `sculpt_paint` are still here.
         Both are Stage 2 targets themselves. **Deleting them takes `curves`
         with them for free**, the same way `transform` dissolved
         `transform_convert_particle.c`.

      #### The link-graph finding, which is the one genuinely new thing

      `bf_editor_sculpt_paint` calls `curves::` seven times but **does not list
      `bf_editor_curves` in its `LIB`**. It links anyway, because
      `bf_editor_space_view3d` does list it, and the final executable merges all
      editor archives. That means:

      - `bf_editor_curves` has exactly **two** declared link consumers:
        `space_view3d` (`CMakeLists.txt:76`) and `undo` (`CMakeLists.txt:33`).
      - The `undo` one is **stale** - `undo_system_types.cc` no longer calls
        `ED_curves_undosys_type`, so `bf_editor_curves` there is dead weight.
        Same category as `bf_editor_physics` in the same file, which was
        removed with `physics`.
      - **`sculpt_paint`'s dependency on `curves` is a link-time accident, not a
        declared one.** It compiles against `ED_curves.h` and resolves at link
        because `space_view3d` happens to pull the archive in. So
        "`sculpt_paint` needs `curves`" is *not* a reason to keep `curves` - the
        dependency direction is the other way round: it is `space_view3d` that
        makes the link work.

      That is worth generalising, because it is the same shape as the
      `overlay_edit_curves.cc` shader borrowing from this round's `physics`
      deletion: **a declaration in a `CMakeLists.txt` is not the dependency
      graph.** Read the graph off the linker, not off the build files - and
      remember that a module can be reachable through an archive it never names.

      **Status: measured, not yet cut.** It needs the `space_view3d` +
      `sculpt_paint` decision first, because that is what decides whether the
      `blender::ed::curves` API can go in one step or has to be severed
      symbol-by-symbol from two modules that are about to be deleted anyway.

      ### `space_topbar` is scoped, and it is not the status bar's twin

      The status bar took one round. The top bar will not, and the reason is
      worth recording before anyone starts it: **the top bar owns two C menu
      types that BLUI keeps using.**

      - `TOPBAR_MT_undo_history`, defined in `space_topbar.c` (~30 lines) and
        invoked by `editors/undo/ed_undo.cc:777` through `WM_menu_name_call()`.
        Undo is core to BLUI, so this menu has to *move* to a kept module before
        the top bar can go - not be deleted with it.
      - `TOPBAR_MT_file_open_recent`, also defined there, and named by
        `keymap_data/industry_compatible_data.py:187` as an `op_menu()` binding.

      Both are additionally listed by name in `interface_template_search_menu.cc`.

      **The Python half is the opposite of the status bar's.** There the whole
      `bl_ui` module had to go. Here `bl_ui/space_topbar.py` must *stay*: it
      defines BLUI's entire main menu bar - `TOPBAR_MT_editor_menus`,
      `TOPBAR_MT_file`, `_edit`, `_window`, `_help`, `_blender`, and the
      BLUI-specific `TOPBAR_MT_blui_components`. It is drawn from
      `bl_ui/space_blui.py:20,37`, which imports `TOPBAR_MT_editor_menus` and
      calls `draw_collapsible()`. Only the `Header` class at
      `space_topbar.py:5` (`bl_space_type = 'TOPBAR'`) may be removed; the menus
      stay, because a window header draws them rather than a top-bar area.

      So the module is named after the space, and the *file of the same name* is
      now mostly menu definitions that have nothing to do with it. Third
      appearance of that pattern, and the largest instance so far.

      The C-side sites, for whoever picks this up - the enum-first method will
      re-derive them, but they are: `rna_space.c` (enum array +
      `rna_Space_refine`), `rna_screen.c` (the `Area.type` setter and the itemf
      filter), `readfile.cc`, `wm_draw.c`, `wm_event_system.cc` (two), `area.cc`
      (two), `screen_ops.c` (six), `screen_user_menu.c`,
      `blenkernel/context.cc` (`CTX_wm_space_topbar`), `interface/resources.cc`,
      `gpencil_utils.c` (two) and `interface_template_search_menu.cc`.

      The `include_all_areas` sentinel at `interface_template_search_menu.cc:1142`
      is already dead: it is true only when the *top bar* runs the menu search,
      and no top-bar area can exist in BLUI. The dummy `ScrArea` at line 515 only
      needs a different non-`SPACE_EMPTY` spacetype, and `SPACE_INFO` will do.

      > **Correction to an earlier estimate here.** Removing the now-dead
      > `include_all_areas` path is *not* a five-minute cleanup of one block at
      > line 505. The flag is read at **six** places - 505, 573, 650, 817 and 882
      > inside `menu_items_from_ui_create()`, plus the parameter on line 428 and
      > the initialisation on 1142 - and they interleave with the normal path
      > rather than sitting in one branch. Budget a real round for it, with a
      > build after each branch, and do not start it believing it is small. That
      > is why it is still there.
      >
      > Read properly, the sites are not all the same kind, which is what makes
      > the job what it is. Three of them - 517, 585 and 894 - are **`if`/`else`
      > pairs where the `else` is the live path**, so each is a
      > *promote-the-else* restructure rather than a deletion. The `if` at 517 is
      > the one that populates `space_type_ui_items`, so promoting its `else` is
      > not mechanical: whatever the live path needs from those arrays has to be
      > established first. The other two are trivial by comparison - 662 is a
      > stale comment, 829 appends a prefix to item names in a branch that never
      > runs.
      >
      > **Now measured, and the advice is to stop short of the last one.** Four of
      > the five branches are gone (`a1c1dcf`, `31b1c61`, `17ca3c7`). The
      > remaining block at 514 should probably **not** be removed, which reverses
      > what the paragraphs above imply:
      >
      > - The loop at 572 has a `continue` in its body (line 656), so it cannot be
      >   replaced by a straight-line pass. With the `Area.ui_type` array gone it
      >   would have to become `for (int i = -1; i < 0; i += 1)` - a loop that
      >   runs once, where the dead block at least reads as a coherent feature
      >   that is merely unreachable.
      > - It orphans four locals (`space_type_ui_items`, `_len`, `_free` and
      >   `wm_contexts`), each of which then has to be hunted down and deleted,
      >   including the one that is assigned but never read and so produces no
      >   warning.
      >
      > Deleting it would make the code *less* readable and no more correct. The
      > honest options are to leave it as documented history, or to remove the
      > whole feature in one pass - the `MenuSearch_Context` plumbing and the
      > `-1` global-context special case go with it - which is a different and
      > larger job than a cleanup.

      ### `editors/space_topbar/` is deleted, and the scope above held exactly

      The module (330-line `space_topbar.c`, 10,327 B) is gone, and the two
      paragraphs above were accurate in every particular: two C menu types moved
      out, the Python file stayed, `SPACE_INFO` took over the dummy spacetype,
      and the `include_all_areas` sentinel was already dead. Eleven C files were
      touched, plus three Python modules.

      The move, first, because the module cannot be deleted until it is done:

      | Menu type | Moved to | Who needed it |
      | --- | --- | --- |
      | `TOPBAR_MT_undo_history` | `editors/undo/ed_undo.cc` (+ `ED_undo.h`) | `ed_undo.cc`'s own `undo_history_invoke()` via `WM_menu_name_call` |
      | `TOPBAR_MT_file_open_recent` | `windowmanager/intern/wm_operators.c` (+ `wm.h`) | `keymap_data/industry_compatible_data.py:187` `op_menu()` |

      Both are registered from new functions - `ED_undo_history_menu_register()`
      called from `ED_spacetypes_init()`, `wm_open_recent_menutype_register()`
      called from `wm_init_exit.cc` after `WM_menutype_init()`. **The idnames are
      deliberately unchanged**: `interface_template_search_menu.cc` names both by
      string, and renaming them would take those search entries with it. The
      module that *defines* a menu and the string that *names* it are independent.

      `ED_undo_history_menu_register()` lives in `ed_undo.cc` rather than in
      `space_api/spacetypes.c` on purpose - the menu's only caller is
      `undo_history_invoke()` three functions above it, so operator and menu stay
      together. That is the same "put the thing with the thing it serves"
      judgement as the particle-cache draw code in the `physics` round.

      #### The enum-first method, and the one site it does not reach

      Removing `SPACE_TOPBAR = 21` from `eSpace_Type` first, then building, is
      again the cheap way to enumerate the call sites - it named about a dozen
      files in one build. The list matches the one written down above, with two
      additions the earlier survey had missed:

      - `blenloader/intern/readfile.cc:2656` and `windowmanager/intern/wm_draw.c:575`
        (a `SPACE_NAME(SPACE_TOPBAR)` in the debug space-name switch).
      - `editors/gpencil_legacy/gpencil_utils.c:94,131` and
        `editors/interface/resources.cc:134` - both plain `case SPACE_TOPBAR:`
        arms that become `default` traffic once the space is gone.

      Three sites needed a **decision** rather than a deletion, exactly as the
      earlier survey predicted. Each got the same treatment: the test is
      *unconditionally true* now, so the guard comes off and the body stays.

      | Site | Was | Now |
      | --- | --- | --- |
      | `screen_ops.c:4114` `region_toggle_poll` | refuses top-bar | refuses nothing; whole `if` removed |
      | `screen_ops.c:4182` `region_flip_poll` | refuses top-bar | same |
      | `screen_ops.c:4298,4319` header-tools menu | hides "Show Header" and the flip/tools block | both shown unconditionally |
      | `screen_ops.c:5480` `space_type_set_or_cycle_poll` | `!= SPACE_TOPBAR` | `!= SPACE_EMPTY` - the remaining true statement, since an empty area is the one that must not be switched |
      | `area.cc:3337` header layout | skips a 1 px offset for top-bar | offset is unconditional |
      | `wm_event_system.cc:6142` region-to-window fallback | keeps top-bar regions as-is | whole `if` removed |
      | `screen_user_menu.c:73-74` | global user-menu slot | `um_array[1] = NULL` - the slot only ever resolved for the top bar |
      | `interface_template_search_menu.cc:1142` | `include_all_areas` from the top bar | `const bool include_all_areas = false` |

      The `space_type_set_or_cycle_poll` line is the one worth marking: deleting
      the top-bar half leaves `area && area->spacetype != SPACE_TOPBAR`, which is
      *not* a tautology - `area` can still be null - so the naive "it is always
      true, simplify it away" reading would have made a null area acceptable.
      It became `SPACE_EMPTY` instead. Check what a predicate is *for* before
      collapsing it.

      #### The Python half, and the trap a fourth time

      This is the failed build's cause, and the earlier section called it
      correctly: **`space_topbar.py` must stay and only its `Header` class goes.**
      The menus - `TOPBAR_MT_editor_menus`, `_blender`, `_file`, `_edit`,
      `_window`, `_help`, `_blui_components` - are BLUI's entire main menu bar and
      are drawn from a *window header*, via `bl_ui/space_blui.py`. A menu carries
      no `bl_space_type`, so menus survive the space's deletion untouched; only
      the `Header` subclass had one.

      The trap then fired anyway, from three panels that were supposed to have
      been repointed and were not:

      ```
      TypeError: validating class: enum "TOPBAR" not found in
      ('EMPTY', 'FILE_BROWSER', 'IMAGE_EDITOR', 'SEQUENCE_EDITOR',
       'TEXT_EDITOR', 'CONSOLE', 'PREFERENCES', 'INFO')
      ```

      `TOPBAR_PT_tool_settings_extra` (line 40), `TOPBAR_PT_name` (647) and
      `TOPBAR_PT_name_marker` (717) still had `bl_space_type = 'TOPBAR'`. **This
      is the identical failure to the status bar's, and it lands in the identical
      place**: the raise happens inside `bl_ui/__init__.py`'s registration loop
      and aborts the rest of it, so the symptom is three *preferences* panels
      missing and the cause is a deleted *top bar*. `check_preferences.py` again
      caught it and no other check did.

      The four panels keep `bl_space_type = 'INFO'` as a **dummy** - they are
      only ever opened as popovers, by name, so any registered space type works.
      `INFO` is chosen because it is the only BLUI space that is never offered in
      the editor-type menu, so a dummy can never be mistaken for a real editor.

      A fourth Python site, `properties_grease_pencil_common.py:369`, had
      `context.space_data.type not in {'VIEW_3D', 'TOPBAR', 'SEQUENCE_EDITOR'}`.
      That is a *set membership* test rather than a class attribute, so it cannot
      raise - it was checked and `'TOPBAR'` removed on correctness, not on
      necessity. Worth separating the two: only the class attribute aborts
      registration.

      #### Two build-iteration lessons, both about stale state

      **`Edit` can silently not persist.** Four separate `Edit` calls in this
      round returned `EBUSY: resource busy or locked` on the first try; the
      retries reported success, and then the file on disk still had the *old*
      text. It happened to `ed_undo.cc` (a `static_cast`), `rna_space.c` (an enum
      array entry) and twice to `space_topbar.py`. **After a retry, re-read the
      region - do not trust the success message.** The build and
      `check_preferences.py` both caught these, but only after a full cycle each.

      **The binary does not read `source/scripts/`.** It reads
      `build/bin/1.0/scripts/`, which the install step populates - and that
      directory was last written by a *full* install. The incremental ninja build
      re-links `BLUI.exe` and does **not** re-copy `scripts/`. So a Python-only
      fix changes nothing until

      ```
      cp -r source/scripts/startup/bl_ui/. build/bin/1.0/scripts/startup/bl_ui/
      ```

      is run by hand. This is the second time this has cost a cycle - the status
      bar round recorded the same thing one section down - so it is worth stating
      as a rule: **after any edit under `source/scripts/`, sync it into
      `build/bin/1.0/scripts/` before running a check, or the check is testing
      the previous revision.**

      #### Verification, all seven scripts, after the build went green

      | Check | Result |
      | --- | --- |
      | `check_editor_set.py` | PASS - 6 startup areas, all BLUI components |
      | `check_preferences.py` | PASS - all 10 kept sections, 5 dropped sections empty |
      | `check_keymap_config.py` | PASS - **116 keymaps**, unchanged |
      | `check_window_isolation.py` | PASS - `RESULT_PASS`, 3 windows, 3 distinct screens |
      | `check_component_window.py` | PASS - `RESULT_SETTINGS_WINDOW PASS` |
      | `check_save_isolation.py` | PASS - text editor wrote the real file on disk |
      | `click_sweep.py` | PASS - 144 clicks, no crash |

      `check_workspace_geometry.py` also run (not part of the seven): all six
      component areas `2560x1377`, full-window, as before.

      The keymap count is **116 for the third module running**. `space_topbar`
      had no keymap of its own, and `TOPBAR_MT_file_open_recent` is a *menu*
      binding rather than an operator registration, so the macro
      `property_unset()` trap could not have applied here - the count confirms it
      rather than merely asserting it.

      Also gone with the module: `SpaceTopBar` in `DNA_space_types.h`,
      `CTX_wm_space_topbar()` (`blenkernel/context.cc` + `BKE_context.h`),
      `ED_spacetype_topbar()` (`ED_space_api.h`), `bf_editor_space_topbar` from
      `editors/space_api/CMakeLists.txt`, and `add_subdirectory(space_topbar)`.
      `bTheme.space_topbar` was **kept as a shell**, the same decision as
      `space_statusbar` and `SpaceProperties`: it is user-preference colour data
      for a space that cannot exist, and removing it reaches into the verified
      preferences panels.

      `SPACE_TOPBAR = 21` is retired rather than reused, matching slot 22
      (`SPACE_STATUSBAR`) and slot 14 (`SPACE_SCRIPT`). Three dead slots now, and
      every enumerator in that enum is explicit, so no renumbering pass is needed.

      ### `object` + `space_view3d` (2.3 MB) measured: they are the apex, and the apex is load-bearing

      Measured on 2026-09-16 with the same script used for `physics` and
      `curves`, extended to bucket each consumer by whether it is a Stage 2
      target or a module BLUI keeps. The numbers settle the order recorded
      above, and the answer is not what "delete the apex last" implies.

      | | `editors/object` | `editors/space_view3d` |
      | --- | --- | --- |
      | Files / size | 28 / 1,195,982 B | 41 / 1,147,410 B |
      | Public header | `ED_object.h`, 748 lines | `ED_view3d.h`, 1,381 lines |
      | Declared symbols | 136 | 127 |
      | Symbols with **zero** external users | **0** | **0** |
      | Files including the header | 106 | 158 |
      | Consumers that are themselves doomed | 41 | 80 |
      | Consumers that **stay** | **25** | **38** |

      Both headers are 100% live. There is no dead enumeration to take first,
      the way there was for the four space types - every one of the 263 exported
      symbols has at least one caller outside the module, and the big ones have
      a lot: `ED_view3d_ob_project_mat_get` **26 files**,
      `ED_view3d_viewcontext_init` 23, `ED_view3d_project_float_v2_m4` 22,
      `ED_object_base_select` 16, `ED_object_base_activate` 13.

      So the two modules are not apexes in the dependency-cone sense - a node
      nothing depends on. They are apexes in the *reverse* sense: the two
      modules with the largest export surface in the editor layer, and 63 kept
      files sit on top of them. Deleting them is not a cut, it is a
      re-homing exercise for 263 functions.

      #### Where the kept consumers actually are

      `ED_object.h` - 25 kept files, and **7 of them are `makesrna/intern`**:

      ```
       7  makesrna/intern        (rna_object.c 16 syms, rna_layer.c,
                                  rna_pose.c, rna_constraint.c,
                                  rna_object_api.c, rna_object_force.c, rna_scene.c)
       6  editors/gpencil_legacy (gpencil_data/edit/armature/convert/trace_ops/utils)
       2  editors/interface     (interface_ops.cc, interface_templates.cc)
       2  modifiers/intern      (MOD_nodes.cc, MOD_particlesystem.cc)
       1  each: makesdna, editors/util, editors/undo, windowmanager/intern,
                editors/render, editors/space_api, editors/screen, editors/space_image
      ```

      `ED_view3d.h` - 38 kept files, and the distribution is different:

      ```
      12  editors/gpencil_legacy  (the whole annotation/gpencil paint stack)
       6  draw/engines            (overlay grid/fade/gpencil, eevee, compositor)
       4  windowmanager/intern    (wm_draw, wm_operators, wm_event_system, wm_files)
       3  draw/intern             (draw_manager, draw_manager_text, draw_view)
       3  editors/render          (render_opengl, render_update, render_preview)
       2  makesrna/intern         (rna_space.c, rna_space_api.c)
       2  windowmanager/gizmo     (wm_gizmo, wm_gizmo_map)
       2  editors/interface      (the two eyedroppers)
       1  each: editors/screen, windowmanager/xr, blenkernel/intern,
                editors/space_sequencer
      ```

      Three of those buckets are decisive, and none of them is a Stage 2 target:

      - **`makesrna/intern`.** `rna_object.c` needs 16 `ED_object_*` functions -
        modifier add/remove/clear/move, constraint active set and update, facemap
        add/remove, parent, shaderfx add/clear/remove. The RNA layer *is* the
        object model's public API. This is the same shape as `space_buttons`,
        whose RNA callbacks were the reason it could not be cut mechanically.
      - **`editors/gpencil_legacy`.** 6 files for `ED_object.h` and **12** for
        `ED_view3d.h`. Grease-pencil annotation painting is a component BLUI
        keeps, and it is a 3D-context painter: it needs
        *(these figures are the pre-annotation-cut counts. The
        re-measurement after `feec67c6313` is **5 and 11**, and it shows both
        buckets are the GP **object**, not annotation - the sentence below is
        wrong about that. Kept for the record; read the re-measurement.)*
        `ED_view3d_depth_read_cached`, `_depth_override`, `_autodist_simple`,
        `_calc_camera_border`, `_project_float_global` and friends to map screen
        input onto the scene. **This is the finding that decides `space_view3d`:**
        the annotation stack is not using the *viewport* - it is using the
        *projection math*, which happens to live in `space_view3d`.
      - **`windowmanager`.** 4 + 2 + 2 + 1 files, including `wm_draw.c`,
        `wm_operators.c`, `wm_files.cc` and the whole gizmo subsystem. The
        window manager cannot be deleted and cannot easily be un-taught the
        viewport.

      #### The verdict

      **`object` and `space_view3d` are measured and rejected as a single
      mechanical deletion.** They were listed in the brief as the dependency
      cone's apex and therefore the last thing to do, on the theory that the
      first three steps would shrink what they carry. Steps 1-3 are done, and
      they do not shrink it: `physics`, `curves` and `space_topbar` contributed
      **zero** of the 25 + 38 kept consumers. The measurement that mattered was
      of an edge none of the three touched.

      What would have to happen instead, in the order the evidence supports:

      1. **`object` cannot be deleted before the object model's RNA is
         re-decided.** `rna_object.c`'s 16 calls are modifier and constraint
         operations exposed to Python. Either those RNA properties go (a
         product statement: BLUI has no modifier stack) or the functions they
         call move somewhere kept. That is 16 functions in one file, and it is
         the cheapest of the three buckets.

         *(Re-measured after the annotation cut - see "`object` +
         `space_view3d` re-measured" below. This bucket is unchanged at 7
         files for `ED_object.h`; it is still the cheapest.)*
      2. **`space_view3d` cannot be deleted before the projection math is
         separated from the viewport.** `ED_view3d_project_*`,
         `ED_view3d_win_to_3d_*`, `ED_view3d_depth_*`,
         `ED_view3d_calc_zfac` and `ED_view3d_ob_project_mat_get` are
         *arithmetic over a `RegionView3D`*, not viewport UI. They are in
         `space_view3d` because that is where Blender put them, and the
         annotation painter, the gizmo subsystem and the draw engines all
         depend on them. Moving them to a kept module would shrink the kept
         surface substantially - but it is a refactor, not a deletion, and it
         would want its own build-and-verify round before anything is removed.
      3. **`gpencil_legacy` (18 files across the two headers) is the consumer to
         look at first.** It is the single largest kept bucket and it is the one
         most entangled with 3D projection. If annotation painting is in scope
         for BLUI, it pins the projection math in place and the honest answer is
         that `space_view3d` shrinks but does not disappear.

         **CORRECTED.** LHT answered that annotation is *not* in scope, and
         the projection math is *still* pinned - the bucket turned out to be
         the GP object, not annotation. See the re-measurement below.

      That third point is a **product question for LHT, not a technical
      one** - the same shape as the particle question that unblocked `physics`,
      and the reason this section is a measurement rather than a deletion.
      Until it is answered, `object` and `space_view3d` stay, and the honest
      progress report for this target is "measured, blocked on a product
      decision, nothing deleted".

      For the record, the same trick that made the four space types cheap does
      **not** apply here, and this is worth stating plainly because it was the
      working assumption: those modules had a dead *enum surface* that could be
      removed first, and the compiler then named every call site. `ED_object.h`
      and `ED_view3d.h` have no dead surface at all - removing any symbol
      breaks a link immediately. There is no enum-first move available.

      ### The annotation question was answered, and it opens `gpencil_legacy` (1.6 MB)

      LHT's answer to point 3 above was **no, annotation drawing is not kept**.
      That removes the single largest kept consumer of `space_view3d`, and the
      next target is therefore not `object` or `space_view3d` - it is
      `editors/gpencil_legacy/` itself, which is **35 files / 1,597,392 B**,
      larger than `object` (1.19 MB) and `space_view3d` (1.15 MB) individually.
      Scoped here, not yet cut.

      #### The distinction that decides the whole job

      Grease Pencil is two unrelated things that share one module:

      - **`OB_GPENCIL_LEGACY`** - a real object type, a 3D drawing medium, with
        its own modifier stack (`gpencil_modifiers_legacy/`, 39 files), its own
        node/mask/palette system, its own paint and sculpt and weight brushes,
        and its own file format. `object.cc` has it in **fifteen** switch arms.
        *(Measured in full later: 124 files / 3.15 MB across `editors/`,
        `blenkernel/` and `draw/`.)*
      - **Annotation** - the screen-level scratch layer you scribble on in any
        editor. It is `bGPdata` hanging off a `Screen`, not off an `Object`, and
        it is drawn by `ED_annotation_draw_view2d()` /
        `ED_annotation_draw_view3d()` / `ED_annotation_draw_2dimage()`.

      Both halves live in `editors/gpencil_legacy/` and both are in
      `ED_gpencil_legacy.h` (86 exported functions, 24 consuming files outside
      the module). **Retiring annotation does not retire the object** - which is
      the good news, because the object half is the expensive one.

      #### What is actually reachable in BLUI

      Swept `bl_ui/space_blui.py` and `bl_ui/space_topbar.py`:

      - `space_blui.py` has **zero** references to annotation, gpencil or
        `GPENCIL`. The annotation tool is not in BLUI's tool system, and BLUI
        has no 3D viewport to annotate in.
      - `space_topbar.py` has five, and **all five are file-format menu items**:
        "SVG as Grease Pencil", "Grease Pencil as SVG", "Grease Pencil as PDF",
        each guarded on `bpy.app.build_options.io_gpencil`. They are about the
        *object* type and `io/gpencil/`, not annotation.

      So the annotation layer is unreachable from BLUI's UI. It survives only
      because kept draw paths still call into it.

      #### The kept consumers of the annotation API - 8 files

      These are the call sites that keep annotation alive, and every one is a
      draw pass in a module BLUI keeps:

      | File | Symbols | Stays? |
      | --- | --- | --- |
      | `draw/intern/draw_manager.c` | `ED_annotation_draw_view2d`, `_view3d` | yes - the draw manager itself |
      | `editors/space_sequencer/sequencer_draw.c` | `ED_annotation_draw_2dimage`, `_view2d` | **yes - a BLUI component** |
      | `editors/render/render_opengl.cc` | `ED_annotation_draw_ex` | yes (viewport render) |
      | `editors/space_node/node_draw.cc` | `ED_annotation_draw_view2d` | doomed (node editor) |
      | `editors/space_clip/clip_draw.cc` | `ED_annotation_draw_2dimage`, `_view2d` | doomed (clip editor) |
      | `editors/undo/ed_undo.cc` | `ED_gpencil_session_active` | yes |
      | `editors/util/ed_util.cc` | `ED_gpencil_toggle_brush_cursor` | yes |
      | `editors/screen/screen_context.c` | 11 `ED_annotation_*` / `ED_gpencil_data_*` | yes |

      **`sequencer_draw.c` is the one to look at first.** It is a BLUI component
      and it calls `ED_annotation_draw_2dimage()` - that is the annotation layer
      being composited over the video sequencer. Removing annotation means
      removing that call, not moving it: a sequencer has nothing to annotate.
      Same for `render_opengl.cc`, `ed_undo.cc` and `ed_util.cc` - all four are
      call removals, not relocations.

      `draw_manager.c` and `screen_context.c` are the two that need care, because
      they are the annotation *dispatch*: `screen_context.c` registers 11 context
      members (`ED_annotation_data_get_pointers` and friends) whose whole job is
      to make `bpy.context.annotation_data` resolve. Those are the RNA-facing
      half and go with the feature.

      #### The keymap trap applies here, and it is large

      This is the part that makes it a real round rather than an afternoon. All
      **three** registration entry points are live in `ED_spacetypes_init()`:

      ```
      spacetypes.c:87   ED_operatortypes_gpencil();
      spacetypes.c:167  ED_operatormacros_gpencil();
      spacetypes.c:184  ED_keymap_gpencil(keyconf);
      ```

      and the keymap data names **63 distinct gpencil operators**:

      | File | Distinct `gpencil.*` / `GPENCIL_OT_*` names |
      | --- | --- |
      | `keymap_data/blender_default.py` | 39 |
      | `keymap_data/industry_compatible_data.py` | 24 |

      That is the largest keymap-data dependency measured in this whole effort -
      `space_script` had one binding, `physics` and `curves` had none. And
      `ED_operatormacros_gpencil()` is one of the three surviving `ED_operatormacros_*`
      calls, so `property_unset()` is in play: **the operator registration and
      all 63 keymap-data entries have to be removed in the same step**, or the
      key configuration collapses the way it did when `ED_operatormacros_mesh()`
      was cut alone (135 keymaps → 7).

      Also `keymap_data` and `bl_ui` are not the only Python: four `bl_ui`
      modules touch it - `properties_grease_pencil_common.py` (29 ops),
      `space_toolsystem_toolbar.py` (16), `properties_paint_common.py` and
      `space_image.py` (1) - and `properties_grease_pencil_common.py` is the
      shared mixin, so its `AnnotationDataPanel` class is the annotation half
      while the rest is the object half. It has to be split, not deleted.

      #### Recommended split, in order

      1. **Annotation first, and only annotation.** Cut
         `annotate_paint.c` + `annotate_draw.c` (126 KB) and the eight draw call
         sites above, the `ED_annotation_*` declarations, and the
         annotation-specific context members in `screen_context.c`. This is a
         coherent product statement - "BLUI has no annotation scratch layer" -
         and it does not touch the object.
      2. **Then re-measure `object` and `space_view3d`.** The `gpencil_legacy`
         bucket in the target-4 table was 6 files for `ED_object.h` and **12**
         for `ED_view3d.h`, and most of the 12 are the annotation painter's
         depth/projection calls. Step 1 should take them out of the table; how
         much of the remaining 25 + 38 it takes has to be measured, not assumed.

         **DONE - see the re-measurement section below.** The answer is 1 and
         1, not 6 and 12; "most of the 12 are the annotation painter's" was
         false.
      3. **The `OB_GPENCIL_LEGACY` object is a separate decision**, and a much
         bigger one: 15 switch arms in `object.cc`, the whole
         `gpencil_modifiers_legacy/` tree, `rna_gpencil_legacy.c` +
         `rna_gpencil_legacy_modifier.c`, `io/gpencil/`, and the three file
         menu items in `space_topbar.py`. Worth asking separately - if BLUI is a
         file browser, a text editor and a viewer, a 3D drawing object is out of
         scope, but it is LHT's call and it is not implied by the annotation
         answer.

         **UNDER-SCOPED. Measured in full below: 124 files / 3.15 MB**, and the
         core is in `blenkernel` + `draw`, not `editors/`. Read the
         `OB_GPENCIL_LEGACY` section before acting on this list.

      **Status: scoped, nothing deleted.** The honest summary is that
      "annotation is not kept" converts target 4 from *blocked* to *unblocked*,
      and identifies `gpencil_legacy` as the next 1.6 MB - but the 63-entry
      keymap coupling and the object/annotation split mean it wants its own
      round with its own build and verify, exactly like every other module here.

      ### `object` + `space_view3d` re-measured after the annotation cut: the bucket was mislabelled

      The scoping round above estimated that annotation was worth **6 files** of
      `ED_object.h`'s kept surface and **12** of `ED_view3d.h`'s. Those figures
      were the product question's whole justification - "annotation painting is
      the single largest kept consumer of `space_view3d`, so retiring it
      unblocks the projection math." The files have now actually been deleted
      (`feec67c6313`), so the estimate can be re-run against the tree instead of
      carried forward. **Both numbers are wrong, and they are wrong in the
      direction that matters.**

      | | `ED_object.h` | `ED_view3d.h` |
      | --- | --- | --- |
      | before annotation cut | 25 kept files | 38 kept files |
      | **after** annotation cut | **24** kept files | **37** kept files |
      | estimated drop | 6 | 12 |
      | **actual drop** | **1** | **1** |

      One file each. Both are the same class of diff: `gpencil_legacy` went from
      6 to 5 files on `ED_object.h` and from 12 to 11 on `ED_view3d.h`, because
      the two files that actually died (`annotate_draw.c`, `annotate_paint.c`)
      took their own includes with them. Nothing else moved.

      #### Why the bucket was mislabelled

      The old table described the 12 as *"the whole annotation/gpencil paint
      stack"* and read the number as annotation debt. Re-run per file, the 11
      survivors on `ED_view3d.h` are:

      ```
       7  gpencil_paint.c, gpencil_fill.c, gpencil_utils.c, gpencil_primitive.c,
          gpencil_sculpt_paint.c, gpencil_convert.c, gpencil_edit.c
          -> OB_GPENCIL_LEGACY paint/fill/sculpt brushes, not annotation
          ED_view3d_depth_override, _depth_read_cached, _depth_read_cached_seg,
          _depths_free, _calc_zfac, _project_float_global, _pixel_size
       3  gpencil_select.c, gpencil_uv.c, gpencil_intern.h
       1  gpencil_ops.c
      ```

      Not one of them is annotation. They are the **grease-pencil object's**
      3D painters, and they ask `space_view3d` the same question annotation did:
      "turn this screen coordinate into a scene-space point using the cached
      depth buffer." That is why deleting the annotation half changed nothing -
      it was never the load.

      The same mislabel is visible on `ED_object.h`: the surviving
      `gpencil_legacy` consumer count is 5, and all five are `gpencil_data.c`,
      `gpencil_edit.c`, `gpencil_armature.c`, `gpencil_convert.c`,
      `gpencil_trace_ops.c` - object-side files.

      #### What this changes

      The record above reads: *"`gpencil_legacy` (18 files across the two
      headers) is the consumer to look at first... If annotation painting is in
      scope for BLUI, it pins the projection math in place; if it is not, the
      projection math is unblocked."* **LHT answered that annotation is out of
      scope, and the measurement above says the projection math is still
      pinned - by the GP object instead.**

      So the dependency did not move; the name on it did. The bucket that holds
      `space_view3d` in place is `OB_GPENCIL_LEGACY`, which is the *other*,
      larger decision the scoping round already flagged as needing its own
      answer (15 switch arms in `object.cc`, all of `gpencil_modifiers_legacy/`,
      `rna_gpencil_legacy.c` + `rna_gpencil_legacy_modifier.c`, `io/gpencil/`,
      three file menu items). **The annotation answer does not unblock target
      4; only the GP-object answer does.**

      #### The same re-measurement, per bucket, unchanged

      Everything else the target-4 table listed is untouched, which is itself
      the finding - `physics`, `curves`, `space_topbar` and `annotation`
      contributed zero kept consumers, so the kept surface is stable at 24 + 37:

      | bucket | `ED_object.h` | `ED_view3d.h` |
      | --- | --- | --- |
      | `makesrna/intern` | 7 | 2 |
      | `gpencil_legacy` | 5 ~~6~~ | 11 ~~12~~ |
      | `editors/interface` | 2 | 2 |
      | `windowmanager` | 1 | 4 + 2 gizmo + 1 xr |
      | `draw/` | 0 | 6 engines + 3 intern |
      | `editors/render` | 1 | 3 |
      | everything else | 8 | 12 |

      The two decisive non-target buckets are unchanged and still decisive:
      `rna_object.c`'s **16** `ED_object_*` calls (the object model's public
      Python API) and the window manager's dependency on the viewport. Neither
      is a function of annotation or of grease pencil.

      #### Status: measured, no deletion, and the blocking question is now the right one

      Target 4 stays where it was - 27 files / 1,194,257 B (`object`) and 40
      files / 1,145,315 B (`space_view3d`) still present - but the *reason* it is
      blocked has been corrected. It is not annotation. The next product
      question to put to LHT is not "is the projection math worth keeping" but
      **"does BLUI ship `OB_GPENCIL_LEGACY`"** - and that one is a bigger
      question than annotation was, because it carries a modifier stack, a
      brush system and a file format along with it.

      No commit for this round: nothing in the tree changed. The measurement is
      recorded here so the next round does not re-derive it, and the two numbers
      it retires - 6 and 12 - are annotated rather than left to look current.

      ### `OB_GPENCIL_LEGACY` measured: 124 files / 3.15 MB, and it is not where the last round said it was

      The re-measurement above ends with the question this section answers:
      *does BLUI ship `OB_GPENCIL_LEGACY`?* That is now the only thing standing
      between the tree and target 4 (`object` + `space_view3d`, 2.34 MB). The
      earlier scoping round described the object as "a real object type, a 3D
      drawing medium, with its own modifier stack" and listed the work as *15
      switch arms in `object.cc`, `gpencil_modifiers_legacy/`, two RNA files,
      `io/gpencil/`, three file menu items*. **That description is too small by
      roughly a factor of two, and it points at the wrong directory.**

      #### The full extent

      | what | files | bytes |
      | --- | --- | --- |
      | `editors/gpencil_legacy/` | 32 | 1,469,321 |
      | `gpencil_modifiers_legacy/` | 39 | 714,040 |
      | `io/gpencil/` | 13 | 60,902 |
      | `draw/engines/gpencil/` (incl. 11 `.glsl` + 2 `.hh`) | 22 | 167,650 |
      | `blenkernel/gpencil*` (10 scattered files) | 10 | 399,683 |
      | `draw/intern/gpencil*` (2 scattered files) | 2 | 48,536 |
      | `makesrna/intern/rna_gpencil_legacy.c` | 1 | 113,594 |
      | `makesrna/intern/rna_gpencil_legacy_modifier.c` | 1 | 230,017 |
      | `makesdna/DNA_gpencil_legacy_types.h` | 1 | 27,697 |
      | `makesdna/DNA_gpencil_modifier_defaults.h` | 1 | 9,941 |
      | `makesdna/DNA_gpencil_modifier_types.h` | 1 | 37,734 |
      | `editors/include/ED_gpencil_legacy.h` | 1 | 23,637 |
      | **total** | **124** | **3,302,752 (3.15 MB)** |

      For scale: that is larger than `object` (1.19 MB) and `space_view3d`
      (1.15 MB) **combined**, and larger than every other module deleted in
      Stage 2 so far put together.

      #### The correction that matters: the core is in `blenkernel`, not `editors`

      The previous round looked only at the editor layer. The GP object's actual
      implementation is 399,683 bytes across **ten `blenkernel` files**:

      ```
      142,435  blenkernel/intern/gpencil_geom_legacy.cc
       92,297  blenkernel/intern/gpencil_legacy.c
       46,421  blenkernel/intern/gpencil_curve_legacy.c
       35,485  blenkernel/intern/gpencil_modifier_legacy.c
       28,211  blenkernel/BKE_gpencil_legacy.h
       21,508  blenkernel/BKE_gpencil_geom_legacy.h
       16,615  blenkernel/BKE_gpencil_modifier_legacy.h
        8,323  blenkernel/intern/gpencil_update_cache_legacy.c
        5,308  blenkernel/BKE_gpencil_update_cache_legacy.h
        3,080  blenkernel/BKE_gpencil_curve_legacy.h
      ```

      plus a full draw engine (`draw/engines/gpencil/`, 22 files including its
      own shader set) and a cache implementation (`draw/intern/draw_cache_impl_gpencil.cc`,
      34,499 B). This is the same shape as the `ED_annotation_data_get_*` lesson
      one level up: **the module name points at the editor, the implementation
      lives in the kernel.** A plan built from `editors/` alone would have
      under-scoped this by ~45%.

      #### How far the dependency actually reaches

      Scanned every non-GP file for GP identifiers (`bGPdata`, `bGPD*`,
      `GPENCIL_`, `BKE_gpencil*`, `ED_gpencil_*`, `OB_GPENCIL_LEGACY`,
      `GpencilModifier`, …). **171 non-GP files** reference them, across every
      layer BLUI keeps:

      | directory | files with GP references |
      | --- | --- |
      | `editors/` | 187 symbol hits |
      | `blenkernel/` | 116 |
      | `draw/` | 80 |
      | `makesrna/` | 38 |
      | `depsgraph/` | 17 |
      | `makesdna/` | 16 |
      | `blenloader/` | 4 |
      | `modifiers/`, `windowmanager/`, `gpu/`, `shader_fx/`, `blentranslation/` | 8 total |

      The heaviest single consumers outside the GP tree are the ones that make
      this a cross-cutting concern rather than a leaf: `blenkernel/intern/object.cc`
      (8), `editors/object/object_add.cc` (8), `editors/object/object_transform.cc`
      (8), `editors/object/object_vgroup.cc` (5), `depsgraph/intern/builder/deg_builder_relations.cc`
      (5), `deg_builder_nodes.cc` (4), `editors/animation/*` (keyframe filtering,
      channel drawing), `blenkernel/intern/material.cc` (5), `rna_material.c` (5),
      and `blenkernel/intern/tracking.cc` (4).

      #### What is genuinely reachable in BLUI - measured, not assumed

      | check | result |
      | --- | --- |
      | `bl_ui/space_blui.py` GP/annotation references | **0** |
      | 3D viewport in BLUI's workspace set | **none** |
      | `bl_ui/space_topbar.py` references | **5**, all file-format menu items |
      | `OBJECT_OT_gpencil_add` registration | `editors/object/object_ops.c:86` |
      | `OBJECT_OT_gpencil_add` UI entry points | **one**: `keymap_data/blender_default.py:2156` (`Shift+A`) |
      | GP drawing tools / brushes / sculpt | no reachable entry point |
      | GP preferences panels | removed in the Stage 5 preferences work |

      The five `space_topbar.py` hits are exactly:

      ```
      337  if bpy.app.build_options.io_gpencil:
      338    self.layout.operator("wm.gpencil_import_svg", text="SVG as Grease Pencil")
      362  if bpy.app.build_options.io_gpencil:
      365    self.layout.operator("wm.gpencil_export_svg", text="Grease Pencil as SVG")
      368    self.layout.operator("wm.gpencil_export_pdf", text="Grease Pencil as PDF")
      ```

      Those three menu items are pure **file-format conversion** on an existing
      GP object. They are only meaningful if a GP object can exist in the first
      place - and the only way to create one is `Shift+A` in a 3D viewport, which
      BLUI does not have. **Measured conclusion: in BLUI today, no user can create,
      open, draw on, or export a Grease Pencil object.** The type is reachable
      only from Python (`bpy.data.objects.new(..., type='GPENCIL')`) - the same
      "reachable from RNA" shape that blocked `space_buttons`.

      #### The honest verdict

      This is a **product question with a measured answer at one end and a real
      cost at the other**, and it is LHT's call:

      - **Shipping it costs nothing today.** It compiles, it is unreachable, and
        it is not in BLUI's UI. Leaving it is a defensible choice.
      - **Deleting it is ~3.15 MB and 124 files**, plus edits across **171
        non-GP files** in `blenkernel`, `draw`, `depsgraph`, `makesdna`,
        `blenloader` and all of `editors/object/`. It is materially larger than
        `object` + `space_view3d`, which are themselves measured-and-rejected as
        a single mechanical deletion.
      - **It is not a prerequisite for anything else** *except* the way it pins
        `space_view3d`: 11 of that module's kept consumers are the GP object's
        paint/fill/sculpt brushes, which need `ED_view3d_depth_override` and
        friends. So deleting GP would genuinely unblock `space_view3d` - but it
        would cost more than `space_view3d` was ever going to return.

      **Recommendation, stated as a recommendation and not a decision:** if the
      goal is to shrink the product, `OB_GPENCIL_LEGACY` is a poor next target -
      it is the largest single remaining block, it is entirely unreachable, and
      it buys back less than it costs (it unblocks 1.15 MB of `space_view3d` at
      a price of 3.15 MB plus 171 files of edits). The better argument for doing
      it is **product purity** - "BLUI is a file browser, an image viewer, a text
      editor, a video previewer and a console, and it ships no 3D drawing
      medium" - which is a legitimate reason, but a different one than byte
      count. If that is the reason, it should be its own Stage, not a rider on
      target 4.

      ### The verification suite had a blind spot, and finding it turned up 34 real defects

      **Executed 2026-09-16.** No module was deleted this round. The deliverable
      is a widened check plus a measurement, and the measurement is the
      uncomfortable part.

      The starting point was a known miss: the annotation deletion left two
      `builtin.annotate` references in `industry_compatible_data.py`, producing
      three dangling `wm.tool_set_by_id` bindings, and all seven check scripts
      passed. Two causes, both now closed:

      1. `check_keymap_config.py` read `keyconfigs.active` only, so a preset that
         was not active was never looked at.
      2. Nothing anywhere asserted that a keymap item's `idname` still resolves.
         Counting keymaps cannot see an entry naming an operator that was
         deleted - which is exactly the residue a module deletion leaves.

      #### What the widened check found

      The dangling scan was run for the first time and reports **34 bindings
      across the three presets** - `Blender` 16, `Blender_27x` 13,
      `Industry_Compatible` 5. Each was independently confirmed to raise
      `KeyError` on `get_rna_type()`, against negative controls that resolve
      (`object.gpencil_add`, `image.open`, `image.save`, `text.open`,
      `text.save`), so the scan is not blanket-failing. Re-run three times, same
      numbers.

      | Operator | Presets | Root cause |
      | --- | --- | --- |
      | `view2d.ndof`, `image.view_ndof` | all 3 | ndof operators unregistered |
      | `view3d.select` / `select_box` / `select_lasso` / `select_circle` / `object_mode_pie_or_toggle` | 1-2 | `space_view3d` deleted |
      | `object.duplicate_move`, `duplicate_move_linked` | all 3 | `ED_operatormacros_object()` not called |
      | `collection.create`, `objects_remove`, `objects_remove_all`, `objects_add_active`, `objects_remove_active` | 1-2 | `ED_operatormacros_collection()` not called |
      | `text.uncomment` | `Industry_Compatible` | Text operator unregistered |

      The `object.*` and `collection.*` groups are the ones that matter: they are
      bound in **Object Mode**, which is reachable in workspaces BLUI ships. They
      are the leftovers of the earlier abort fix - the macro *registrations* were
      removed to stop `bl_keymap_utils/io.py` aborting, and the keymap data
      naming them was never removed alongside. That is the same rule the macro
      section above states, applied to a previous round's residue.

      **Two corrections to earlier claims, both from reading the call list
      instead of the comment:**

      * The macro section said `_object()` was "still in". It is not:
        `spacetypes.c` calls only `_file()`, `_sequencer()` and `_gpencil()`.
      * The comment at `spacetypes.c:163` says "the four left - file, sequencer,
        paint, gpencil" while three calls are present.
        `ED_operatormacros_paint()` is defined, declared in `ED_paint.h`, and
        called from nowhere. Its absence is inert only because the one macro it
        registers (`PAINTCURVE_OT_add_point_slide`) appears in no keymap data -
        coincidence, not design.

      #### Deliberate decisions

      * **`DANGLING_ALLOWED` stays empty and the check therefore FAILS today.**
        Parking the unreachable `view3d.*` group in it would also silence
        `object.duplicate_move` and `collection.*`, which are reachable bugs.
        An allowlist filled in to make a suite green is how a suite stops being
        able to fail. The fix is to delete the keymap items, not excuse them.
      * **A shipped preset is not an instantiated preset.** Only `Blender.py`
        loads at startup; `Blender_27x` and `Industry_Compatible` are created on
        demand. At startup `keyconfigs` holds `Blender`, `Blender addon`,
        `Blender user`. Touching `kc.preferences` does *not* materialize them
        (measured; that was the first hypothesis and it is wrong). The check
        tests the preset **file** exists, then activates it **by filepath**.
        `preferences.keyconfig_activate` takes `filepath=`, not `file=` -
        passing `file=` raises `TypeError` inside the timer and the process then
        dies of an access violation, which is how that was found.

      Measured keymap counts, `--factory-startup`: **`Blender` 112,
      `Blender_27x` 103, `Industry_Compatible` 103.**

      Suite result: `check_keymap_config.py` **FAILED (3)**, exit 1 - the three
      per-preset dangling assertions. Everything else in it passes. See
      "Verification suite coverage boundaries" for what each script does and
      does not cover.

      **Nothing else changed this round.** No source was touched, no module was
      deleted, and the binary is unchanged - the script is run from
      `source\blui\tools\` via `--python` and does not need installing.

      Nothing was deleted and nothing was changed this round. No commit: the
      tree is untouched and the README entry is the deliverable.

      ### Annotation is deleted: `annotate_draw.c` + `annotate_paint.c` (126 KB)

      **Executed.** LHT's answer ("annotation drawing is not kept") is now the
      code, not a plan. The two files that *are* annotation are gone:

      | file | bytes |
      |---|---|
      | `editors/gpencil_legacy/annotate_draw.c` | 30,076 |
      | `editors/gpencil_legacy/annotate_paint.c` | 96,266 |
      | **total** | **126,342** |

      `editors/gpencil_legacy/` went from **35 files / 1,597,392 B** to
      **33 files / 1,470,833 B**. `BLUI.exe` went from 42,964,480 to
      42,933,760 bytes.

      #### What "annotation" actually was, confirmed by the deletion

      The scoping round above guessed the split; deleting it proved it. Four
      functions in `annotate_draw.c` were the whole drawing API -
      `ED_annotation_draw_2dimage`, `_draw_view2d`, `_draw_view3d`,
      `ED_annotation_draw_ex` - and every one of them died without taking a
      single object-mode call site with it.

      **But the getters are not annotation-only, and this is the trap.** The
      obvious reading of `ED_annotation_data_get_active()` is "annotation
      helper, delete it." That is wrong. Those four getters are *defined in
      `gpencil_utils.c`*, which survives, and they have **16 call sites in
      surviving files**: 10 in `gpencil_data.c`, 2 in `gpencil_edit.c`, and the
      definitions themselves in `gpencil_utils.c`. `ED_annotation_data_get_active()`
      answers "what is the active GP datablock when the owner is a screen
      rather than an object" - the GP *object* code asks that question too.

      The first attempt deleted both the declarations and the draw API. The
      build would have failed with `LNK2001` at the final link, from files
      nobody would think to look at. Caught by grepping for the symbol after
      deleting the file, before building: **4 declarations restored, 4 draw
      API declarations kept deleted.** The rule that generalises:

      > "This symbol has `annotation` in its name" is not evidence that the
      > symbol is annotation. Check where it is *defined* and who *calls* it.
      > A declaration is cheap to get wrong in the safe direction and
      > expensive to get wrong in the other.

      #### The keymap coupling, resolved in one step

      This was the 63-entry problem the scoping round flagged as the reason
      annotation needed its own round. It did not need a special technique -
      it needed the *same* technique every other module here needed: **delete
      the operator registration and the keymap data naming it in the same
      step.**

      `GPENCIL_OT_annotate` was registered at `gpencil_ops.c:541` and named in:

      - `blender_default.py` — 5 entries inside `km_grease_pencil`, plus 4
        whole keymaps (`Generic Tool: Annotate`, `Annotate Line`,
        `Annotate Polygon`, `Annotate Eraser`), plus the `op_tool_cycle("builtin.annotate")`
        line, plus the 4 calls in the keymap list.
      - `properties_grease_pencil_common.py` — the tool-palette buttons.
      - `space_toolsystem_toolbar.py` — `_defs_annotate` (128 lines) and 5
        `*_tools_annotate` splices across two `ToolSelectPanelHelper`s.

      Done together, the keymap config loads fully: **112 keymaps**. Nothing
      was silently dropped, which is the failure mode when they are done apart
      (`bl_keymap_utils/io.py` calls `property_unset()` on macro sub-properties
      and *raises*, so a dangling macro reference takes the whole config down
      to a handful of keymaps rather than warning).

      #### The Python half needed a split, not a deletion

      `properties_grease_pencil_common.py` is a shared mixin module. Two of its
      classes are annotation (`AnnotationDataPanel`, `AnnotationOnionSkin`),
      one includes annotation in its name but is not (`GPENCIL_UL_annotation_layer`
      is the layer list for a *GP object*), and the rest are GP-object panels
      that must stay. Deleting the module was never an option.

      What had to go, and why each one:

      | site | why |
      |---|---|
      | `AnnotationDrawingToolsPanel` | 4 `gpencil.annotate` operators |
      | `AnnotationDataPanel` | the panel body; reads the deleted context members |
      | `AnnotationOnionSkin` | same |
      | `GPENCIL_UL_annotation_layer` | only reached through the deleted panels |
      | `IMAGE_PT_annotation` (`space_image.py`) | subclasses `AnnotationDataPanel` |
      | `SEQUENCER_PT_annotation`, `SEQUENCER_PT_annotation_onion` | same |
      | `_defs_annotate` + its splices (`space_toolsystem_toolbar.py`) | the tool definitions |

      #### Two live sites the scoping round had marked as doomed

      The scope above listed `node_draw.cc` and `clip_draw.cc` as "doomed
      (node editor)" and "doomed (clip editor)". Measured this round: **both
      modules are still in the build.** `editors/space_node/CMakeLists.txt` and
      `editors/space_clip/CMakeLists.txt` both exist and both are compiled -
      only the *registry* entries are gone, which is the same distinction the
      preferences work hit ("being undrawable is not the same as not existing").
      Their annotation calls were removed as real edits, not left for a future
      deletion.

      #### A dangling call site the file deletion did not catch

      `sequencer_draw.c` had already lost its `sequencer_draw_gpencil_overlay()`
      function, but the *call* to it survived at line 2216, along with the
      `draw_gpencil` local that gated it. Catching this is the same lesson as
      the `versioning_cycles.c` double-entry case: **deleting a definition does
      not find its callers.** Removing the file first and letting the compiler
      work through the remainder found it once the build got far enough.

      #### Verification - all seven scripts, real window where required

      | script | result |
      |---|---|
      | `check_editor_set.py` | **PASS** |
      | `check_preferences.py` | **PASS** |
      | `check_keymap_config.py` | **PASS** - 112 keymaps loaded |
      | `check_window_isolation.py` | **PASS** |
      | `check_component_window.py` | **PASS** |
      | `check_save_isolation.py` | **PASS** - round-trip through the text editor |
      | `click_sweep.py` | **PASS** - 144 clicks, no crash |

      `check_preferences.py` is the one that matters here, and it failed twice
      before it passed - both times for a reason worth writing down.

      **Failure 1: a dangling import.** Removing `AnnotationDataPanel,` from
      `space_image.py` left an empty `from bl_ui.properties_grease_pencil_common
      import ()`, which is a `SyntaxError`. `bl_ui/__init__.py` swallows it and
      aborts the rest of the registration loop, so the symptom was *missing
      preferences panels* and the cause was in the *image editor* module. Same
      shape as the top-bar round; the same script caught it. `space_sequencer.py`
      had the identical bug. **When deleting a name from a multi-line import,
      delete the statement - and syntax-check every file in `bl_ui/` before
      building**, which is cheaper than a build round trip.

      **Failure 2: two registrations left behind.** `screen_context.c` kept
      `register_context_function("annotation_data", screen_ctx_annotation_data)`
      and the `_owner` twin at lines 1242-1243, pointing at functions that no
      longer existed. This one was a real `error C2065` and the only genuine
      compile error of the round.

      #### Build environment: the toolchain was not broken; the sandbox was

      Four consecutive builds failed with `fatal error C1083: cannot open
      stdio.h` in files that had nothing to do with this change. **None of it
      was caused by the deletion**, and the diagnosis is worth keeping because
      it will recur:

      - `build.cmd` calls `vcvars64.bat`, which finds the Windows SDK include
        directories by running `reg.exe`.
      - The sandbox blacklists `reg.exe`. vcvars cannot complete, so `INCLUDE`
        holds only the three MSVC paths and no UCRT path.
      - The MSVC `include` directory is also missing its CRT headers
        (`stdio.h`, `stdlib.h`, `string.h`, `stddef.h`, `time.h`, `math.h` all
        absent; only `setjmp.h` present). The Windows SDK `ucrt` directory has
        all of them.

      **The toolchain is fine.** Supplying the SDK paths by hand
      (`_build_sandbox.cmd` at the repo root) makes the same tree compile. That
      file is a sandbox workaround, not part of the build: on a normal machine
      plain `build.cmd` works and it is unnecessary. It also pins `-j1`,
      because parallel `cl.exe` invocations intermittently get `Permission
      denied` creating their `.obj` under the sandbox.

      The other false signal to ignore: `Permission denied` / `cannot open
      compiler-generated file ... .obj` on a handful of unrelated files is a
      transient sandbox write collision, **not** a code error. Re-running
      clears it. Do not go looking for a cause in the source.

      #### Status: deleted, built, verified, committed

      Target 4's first half is done. `object` and `space_view3d` remain, and
      the scoping round's estimate of what annotation was worth to them - 6
      files for `ED_object.h`, **12** for `ED_view3d.h` - can now be
      *re-measured* against the tree rather than assumed, because the files are
      actually gone this time.

      ### `editors/space_statusbar/` is deleted, and the Python half is not optional

      The status bar - asked for in the original brief ("remove Blender's top bar
      and status bar") - and the smallest space left at 5 KB. The C side is a
      dozen sites across eight files, which the build enumerates exactly once
      `SPACE_STATUSBAR` is removed from the enum: `rna_space.c`, `rna_screen.c`,
      `interface_template_search_menu.cc`, `interface/resources.cc`,
      `screen_ops.c`, `screen_edit.c`, `area.cc`, `wm_event_system.cc`,
      `wm_draw.c` and `readfile.cc`. Removing the enum first and letting the
      compiler list the call sites is much cheaper than grepping for them.

      Two cascade rather than being one-liners. `screen_ops.c`'s status-bar
      context menu was the **only** caller of
      `ed_screens_statusbar_menu_create()`, so the function is orphaned and has
      to go with the branch. `wm_event_system.cc` had a whole function whose job
      was to find the status-bar area; it now returns null.

      **The part worth remembering is Python.** Deleting the C module is not
      enough. `scripts/startup/bl_ui/space_statusbar.py` registers a `Header`
      with `bl_space_type = 'STATUSBAR'`, and with the enum gone
      `register_class` raises

          TypeError: validating class: enum "STATUSBAR" not found in (...)

      That is raised inside `bl_ui/__init__.py`'s registration loop and **aborts
      the rest of it**, so the userpref panels in `editing`, `save_load` and
      `file_paths` silently never registered. `check_preferences.py` failed with
      three empty sets while every other check passed - a failure surfacing
      nowhere near its cause, since the symptom was missing *preferences* panels
      caused by a deleted *status bar*.

      So: a space-type deletion has a Python half, and the check that catches it
      is `check_preferences.py`, not the C build. `bpy_types.py`'s
      `WorkSpace.status_text_set()` also imported that module to patch its draw
      function; it now only stores the text, since there is no status bar to draw
      it into.

      One more thing for next time: the binary loads scripts from
      `build/bin/1.0/scripts/`, not `source/scripts/`. Deleting a `bl_ui` file
      changes nothing until the build's install step copies it - the first re-run
      after the fix failed for exactly that reason.

      The `bTheme.space_statusbar` slot and its `ThemeSpaceStatusBar` RNA are
      deliberately left as shells, the same decision as for `SpaceProperties`:
      they are user-preference colour data for a space that can no longer exist,
      and removing them reaches into the verified preferences panels.

      ### `space_buttons` is deleted, in four layers

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


## Packaging (portable ZIP)

BLUI ships as a **portable ZIP**, not an installer. The build tree at
`build/bin` is already a complete, runnable distribution; packaging is a
*selection* step, not a compilation step.

    python D:\BlenderUI\_package.py scan    # show what ships and what does not
    python D:\BlenderUI\_package.py stage   # copy into dist\BLUI-1.0.0-windows-x64
    python D:\BlenderUI\_package.py zip     # stage + zip + read the archive back

Output: `dist\BLUI-1.0.0-windows-x64.zip`.

### Do not run `cmake --install`

`source/creator/CMakeLists.txt` contains

    install(CODE "file(REMOVE_RECURSE ${TARGETDIR_VER})")

`${TARGETDIR_VER}` is `1.0`, so `cmake --install` **deletes `build/bin/1.0/`
first** - the directory holding every runtime script, datafile and the embedded
Python - and repopulates it from the install rules. Those rules are not the same
set (`WITH_PYTHON_INSTALL`, the `blui/tools` tree and the debug `.cmd` wrappers
are all install-rule casualties), so a naive install silently produces a tree
that differs from the one that was tested. Copy from `build/bin` instead.

### The allowlist, and why not a blacklist

`_package.py` names the top-level entries that ship (`INCLUDE_TOP`) and drops
individual files inside them by rule (`DROP_FILES`). A blacklist would silently
carry anything a future build adds; an allowlist *omits* it - which is also
silent, just in the other direction. So `report_scan()` prints three numbers
rather than two:

  - **KEEP** - files copied.
  - **DROP** - files inside a shipped tree that a rule excluded, with the reason.
  - **NOT COVERED** - top-level entries the allowlist never mentions. Neither
    shipped nor dropped. This dimension is the failure mode of an allowlist and
    is why it is printed explicitly rather than left implied.

Measured, 2026-09-16:

| | |
| --- | --- |
| `build/bin` source | 3,931 files, 409.2 MB |
| shipped | 3,744 files, 338.8 MB |
| dropped inside shipped trees | 168 files, 9.3 MB |
| not covered (top level) | 19 files, 61.0 MB |
| ZIP on disk | 3,745 entries, 119.2 MB |

Of the 409 MB source, **155 MB is build residue**: `BLUI.pdb` alone is 44.8 MB,
`makesrna.pdb` 8.0 MB, and the code generators (`makesdna`, `makesrna`,
`datatoc`, `datatoc_icon`, `msgfmt`, `smaa_areatex`) are needed to *compile* BLUI
and never to run it. Shipping them would have made the download 2.5x larger for
nothing.

Two files that look like junk are kept deliberately:
`numpy/core/lib/npymath.lib` and `numpy/random/lib/npyrandom.lib` are numpy's own
static import libraries, shipped by upstream numpy. The `.lib` drop rule names
`BLUI.lib` exactly, not the extension, to avoid taking them.

`oculus.json` is an OpenXR runtime manifest pointing at a hardcoded
`C:\Program Files\Oculus\...` path. It is not referenced anywhere in the source
tree. Excluded.

`blui/tools/` **is not in `build/bin`** and therefore not in the ZIP - the
verification suite is not product code. It lives in `source/blui/tools/` and is
run from there against a packaged `BLUI.exe`.

### Acceptance test

Packing is not proven by matching file counts. `_extract_test.py` unzips the
archive to a clean directory unrelated to the build tree, then runs the two
suite checks that support `--background` against the *extracted* executable:

    BLUI.exe --factory-startup --background --python check_editor_set.py
    BLUI.exe --factory-startup --background --python check_preferences.py

Both must report PASS from inside the extracted tree. That exercises the
archive itself, so a path broken by packaging, a file missed by the allowlist,
or an archive Windows cannot open fails here instead of on the user's machine.

The five checks that need a real window (`check_keymap_config`,
`check_window_isolation`, `check_component_window`, `check_save_isolation`,
`click_sweep`) cannot run headless and are therefore **not** part of packaging
acceptance. The package's job is to load the same runtime; the window checks
test behaviour, not contents.

### Portable mode

Configuration defaults to `%APPDATA%\BLUI\`. It is redirected by **environment
variable**, not by placing a `config` folder next to the executable - there is no
"detect a local config and switch" branch in the code:

    BLUI_USER_CONFIG, BLUI_USER_DATAFILES, BLUI_USER_SCRIPTS, BLUI_USER_AUTOSAVE

Verified, not assumed: with `BLUI_USER_CONFIG` set,
`bpy.utils.user_resource('CONFIG')` returns that path
(`blenkernel/intern/appdir.c:639`).

### Known packaging gap (not yet fixed)

`build_files/cmake/packaging.cmake:109-110` still names `blender-launcher` for
`CPACK_PACKAGE_EXECUTABLES` / `CPACK_CREATE_DESKTOP_LINKS`, and lines 85-86 still
build the install directory as `Blender Foundation/Blender 3.6`. The target now
outputs `BLUI-launcher.exe`. This affects only the CPack/NSIS installers, which
BLUI does not currently ship - the portable ZIP path above does not read these
variables. Left alone rather than half-fixed; if an installer is ever wanted,
these four lines are the first thing to change.

