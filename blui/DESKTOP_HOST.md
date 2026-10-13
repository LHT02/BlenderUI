# Desktop host integration and recovery

This is an **explicit opt-in** desktop surface, not a replacement Windows Shell.
Default launch does not alter Explorer. Existing normal Desktop Canvas windows
remain normal windows; only native DESKTOP-role windows with the dedicated
`BLUI.DesktopHost.v1` property are eligible for embedding.

## Architecture

- The main UI creates one native Node Editor canvas per connected display. Its
  existing node tree, transparent file cards, native box selection/dragging,
  groups, thumbnail jobs and layout autosave remain unchanged.
- `desktop_host.start(config_directory)` starts control I/O on a worker thread.
  `reconcile([{handle: "decimal HWND", device: "display device", rect: [l,t,r,b]}])`
  enqueues a fresh topology. Supply **all connected displays** and their exact
  current physical-pixel work areas, including negative monitor origins.
- `tick()` updates the UI heartbeat and returns a RAM-only status. `snapshot()`
  is read-only RAM. `restore()` disables embedding; wait for `pending_restore`
  to become false **and** `completed_serial >= restore()`'s returned command
  serial before owner-side DESKTOP window teardown. `reconcile()` also returns
  its issued command serial. Initial/restored-empty status alone is not an ack
  of a newly queued command; initial completed_serial is zero. `close()`
  enqueues shutdown without a UI-thread process wait.
- Status fields: `enabled`, `attached_count`, `pending_restore`, `need_rebind`,
  `handles`, `state`, `error`, `completed_serial`. These status/message keys are stable English IDs
  and should be localized by the owner UI, not parsed as translated text.
- The separate `desktop_host_watchdog.py` discovers the **actual icon host**:
  either Progman or the single top-level WorkerW directly containing
  SHELLDLL_DefView and its direct SysListView32. All are verified against
  GetShellWindow, the genuine Windows-directory Explorer executable, immutable
  process creation time, thread ID and class, with exact parent-chain checks.
- The canvas becomes an interactive front child of that host, rather than a
  wallpaper behind DefView. Windows sends its mouse/keyboard events directly to
  its native HWND; there is no mouse message forwarding, low-level injection or
  synthetic recreation of Blender drag previews. Being a desktop child is the
  basis for Win+D behavior; real version-specific behavior still needs native QA.
- Only the original icon ListView is temporarily hidden. Progman, DefView,
  wallpaper WorkerW and Explorer remain alive and otherwise unmodified. No
  undocumented WorkerW creation message, Shell registry, wallpaper setting,
  Explorer restart, taskbar kill, persistent desktop-icon toggle or foreign
  window z-order change is used.

## Transaction and failure behavior

`desktop_service` is the main-thread glue, not a startup takeover preference.
`enable()` and `restore()` are explicit user actions exposed by
`wm.blui_windows_desktop(action='ENABLE'/'RESTORE')` and
`desktop_ui.draw_settings(layout, context)`. Service state retains only
`(RNA pointer integer, HWND string) → display device` tokens and resolves them
fresh; no Window, Screen, Area, Space or NodeTree object survives between ticks.
It restores any preceding host transaction before creating surfaces, waits for
the saved board profile and an updated isolated monitor snapshot, and reuses
per-monitor layout roots without moving or closing normal user canvas windows.

Topology/work-area change or `need_rebind` first restores and waits for a real
command ack; only then it synchronizes or recreates its own DESKTOP windows.
Disable waits for ack + disabled + no pending rollback, then closes only owned
sources, and never bypasses a held Node interaction guard. Undo/redo only detaches
and preserves canvas windows; file loading/exit closes independent host I/O so
the helper pair restores the Windows icon view. Draw reads RAM-only state and
all new labels pass through the existing localization adapter.

The durable UTF-8/no-BOM journal is published atomically and flushed **before**
the first style, parent or visibility mutation. It stores the original canvas
style/exstyle, owner identity, rectangle, visibility, exact icon host identity
and original ListView visibility. Restoring a desktop originally hidden by the
user never makes its icons visible without permission.

Both the normal helper and an independent recovery process retain kernel
handles for their owner; PIDs are not followed after recycling. The recovery
process confirms READY before any attachment. Owner death, pipe EOF, UI
heartbeat loss, helper death or stalled helper heartbeat requests restoration.
Original Windows icons are restored first, then exact owned canvas windows.
Failed native restoration remains journaled. A recovery witness holds the
session mutex object until recovery finishes, preventing a newer helper from
overwriting a still-running older transaction; generation nonce checks provide
a second barrier. No guard is force-killed while it might be restoring.

Display hotplug/work-area changes, Explorer hierarchy changes and lost canvas
windows restore the old transaction and publish `need_rebind`. The UI must
enumerate fresh native windows and monitors, recreate only its DESKTOP surfaces
as necessary and send a fresh all-display topology. No retained RNA window,
area or HWND may be reused across ticks after native window destruction.

SetParent changes neither WS_CHILD nor WS_POPUP automatically, so the helper
changes only its owned HWND styles. Child placement is mapped from physical
screen coordinates to the verified host's client coordinates. `HWND_TOP` here
means front **sibling under that desktop parent**, never global HWND_TOPMOST.
Restoration does not confuse popup ownership with a child parent.

## Native-owner requirements and compatibility boundary

- Native DESKTOP role has a separate `BLUI_DesktopWindowClass` and dedicated
  role marker and a nonzero per-constructor `BLUI.DesktopInstance.v1` token.
  Journal and every restore action match that instance too, so recycling a HWND
  within the same BLUI process/thread/class cannot target a new canvas.
  Normal GHOST windows are never marked by default. Only this role
  participates in the helper protocol, and it stays outside normal startup
  workspace serialization and taskbar-helper role cleanup.
- Window DPI awareness contexts must compare equal via
  AreDpiAwarenessContextsEqual **before** any SetParent. Cross-process mismatch
  can force a DPI reset of the *whole child process*. The helper refuses it and
  leaves Windows unchanged. It does not reset BLUI process DPI awareness or
  silently downgrade all other windows. Native DESKTOP creation alone uses a
  scoped thread context matching the freshly verified Explorer icon host. The
  scope verifies Explorer's Windows executable path, process epoch and unique
  Progman/WorkerW → DefView → ListView chain, creates the hidden own window,
  verifies its context, then restores the original UI thread context on every
  return path. Normal windows and process-wide DPI remain unchanged. Modern DPI
  APIs are resolved from loaded system User32; unavailable APIs fail closed.
- Win11 raised desktop (including 24H2) is detected by Progman's
  WS_EX_NOREDIRECTIONBITMAP and its child DefView hierarchy. The helper applies
  WS_EX_LAYERED/alpha255 only to its own surface when needed. Rendering support
  and mixed-DPI/multi-display behavior need Win11 hardware QA; Win10 or mocks
  do not prove Win11 compatibility.
- Windows destroys children when their Explorer parent is destroyed. No polling
  watchdog can prevent that contract. The native owner must handle DESKTOP
  WM_NCDESTROY safely: invalidate the HWND immediately, stop GPU swap/resize/
  activate, and queue normal window removal rather than freeing Areas while
  painting. A surviving main/taskbar anchor or last-DESKTOP close policy is
  needed so the app can recreate canvases after Explorer restart.
- Unsupported/ambiguous shell hierarchy, access denial, incompatible DPI,
  incomplete monitor coverage or failed raised-desktop rendering are fail-closed
  errors. Keep an obvious Restore Windows Desktop entry. This module does not
  claim full Explorer replacement or Windows virtual-desktop management.

## Primary references

Independent Win32 implementation; no source block is copied or linked from
Lively or coodesker. The publicly available coodesker repository currently has
no desktop-host implementation source to transplant.

- Microsoft [SetParent](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setparent): style and cross-process DPI contract.
- Microsoft [Window Features](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features): child input, parent destruction, layered children.
- Microsoft [GetWindowDpiAwarenessContext](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowdpiawarenesscontext).
- Microsoft [SetThreadDpiAwarenessContext](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddpiawarenesscontext): returns the original thread context to restore after scoped window creation.
- Microsoft [AreDpiAwarenessContextsEqual](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-aredpiawarenesscontextsequal).
- Lively [WinDesktopCore](https://github.com/rocksdanister/lively/blob/core-separation/src/Lively/Lively/Core/WinDesktopCore.cs) and [DesktopUtil](https://github.com/rocksdanister/lively/blob/core-separation/src/Lively/Lively.Common/Helpers/Shell/DesktopUtil.cs), primary architecture reference for legacy/raised host discovery, not an input-forwarding implementation dependency.

## Verification record

`test_desktop_host.py`: pure tests run without starting any helper, GUI,
Explorer mutation or Windows desktop takeover. They exercise actual state,
protocol and native-wrapper methods using controlled RAM mocks. Actual desktop
rendering, Win+D, parent-destroy recovery and packaged helper lifecycle remain
native-owner QA responsibilities.

`check_desktop_host_native.py` is **primary agent only**, serial, isolated CONFIG
and explicit `BLUI_DESKTOP_QA_ENABLE=1`. It temporarily attaches its own new
DESKTOP windows and restores the real ListView, then terminates only its own
immutable-identity helper to exercise the second guardian. It never sends global
Win+D, kills Explorer or changes normal user canvases. A DPI mismatch is logged
as fail-closed rather than evidence of successful rendering. The subagent has
not run this fixture or taken over the desktop.

Primary-agent fourth native run on Windows 10 build 19045: **PASS, 5.85 seconds**.
Two physical displays had equal child/host DPI context (34); actual attach2,
serial acknowledgement, normal exact style/owner/geometry restoration, reattach,
termination of only the test-owned helper and independent guardian restoration
all passed. The original ListView was already hidden at the baseline and stayed
hidden afterward, preserving that user state. This is not Win11 hardware or
global Win+D testing. Earlier failed runs exposed and fixed intermediate
SetParent(NULL)/WS_CHILD handling and redundant cross-process owner writes.

`check_desktop_service_native.py` additionally exercises the actual registered
ENABLE/RESTORE UI operator and runtime glue, all-display custom Node trees,
real asynchronous preview jobs for two own PNG fixtures, ack-gated own-window
closure and layout reuse on a second enable. It also calls the actual bpy power
menu's conditional draw using a recording layout, never a power action. It is
run by the primary agent on the same Windows 10 host: **PASS, 7.8 seconds**.
Both actual ENABLE/RESTORE cycles, all-display monitor/tree binding, asynchronous
own PNG previews, NORMAL window/screen/area preservation, fake-user layout reuse
after owned-window closure, original ListView state restoration, and conditional
Hibernate menu/confirmation draw passed. No global Win+D or actual power action
was sent. The subagent did not run any desktop takeover or GUI.

Host pure regressions: **30 passed**. Service orchestration pure regressions:
**15 passed**, including a final asynchronous layout-save tail after sources
close. Storage failure does not delay restoration of the Windows desktop; the
error remains available to the UI. Idle service ticks keep only a RAM heartbeat
for an already-started helper, never start takeover by themselves.

### Production creation-context correction (2026-10-13)

The earlier host/service fixtures inadvertently left their discovery backend's
worker-style thread context on the UI thread. Their restoration observations
remain valid, but they were not evidence that production DESKTOP creation
matched Explorer while preserving the original UI context. A new fixture that
restored the original context exposed the mismatch; the native creation scope
above fixes it without weakening the helper's pre-SetParent compatibility check.

The primary agent reran host (including independent guardian recovery after
only its own helper termination), two-cycle/two-display service, and owned fake
parent destruction/focus/save-open fixtures with original context preserved:
all passed. Logs verify original UI thread and existing NORMAL context remain
at the baseline, while only new DESKTOP windows match the host. The owned fake
parent fixture matches context only during creation of its own new STATIC
parent, immediately restoring the UI thread afterward.

`check_desktop_hover_restore_native.py` also proves real own mouse capture and
Node box-selection modal operations block lifecycle changes; a real calculator
button hover does not block actual RESTORE/ack-gated owned-window closure.
Native screenshots confirm button highlight. Ordinary HIGHLIGHT is not itself
a registered modal handler, so the original conservative Node gate is not
required to return true for every hover; source guards verify that gate is
unchanged. New lifecycle and DPI scope/fixture regressions total **19 passed**.

Host/service/hover fixtures retain their small OWN temporary diagnostic folders
after verifying original icon visibility, restore acknowledgement and an empty
recovery journal. They do not recursively delete a directory while independent
guardians may still publish their final empty journal. This is not Win11
hardware, global Win+D, or real Explorer restart evidence.

### Python GIL safety under nested redraw

Packaged screenshot QA with concurrent isolated-client control threads exposed
a legacy native GIL predicate error. `PyThreadState_GetDict()` was used as a
current-thread lock check, although it can observe another thread's current
state and allocate a dictionary itself. A nested screenshot redraw changes
context dictionaries after the operator releases the GIL; the old predicate
could therefore skip necessary acquisition. `PYTHONMALLOC=debug` confirmed an
allocator call without the GIL rather than a wallpaper-specific error.

The predicate now checks `Py_IsInitialized() && PyGILState_Check()`. Existing
conditional acquisition/release in context dictionary handling, code cleanup
and context lookup, plus operator release/restore and draw callback
Ensure/Release, remain balanced and unchanged. It does not disable callbacks,
background worker threads or conservative Node-data lifecycle guards. See the
CPython [GIL-state contract](https://docs.python.org/3.10/c-api/init.html#c.PyGILState_Check)
and [thread-state implementation](https://github.com/python/cpython/blob/v3.10.13/Python/pystate.c).

The primary agent's fixed package passed the real hover/RESTORE fixture and
owned fake-parent destruction/save-open fixture with debug allocation enabled.
Eight focused source regressions pass. `BLUI_DESKTOP_QA_SCREENSHOTS=4` or `8`
extends the two original screenshot phases for bounded, real redraw stress;
default remains two screenshots. These regressions are not proof against every
graphics-driver, external shell-hook or COM hang.
