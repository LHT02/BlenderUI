# Native taskbar space reservation and size preferences

Taskbar settings use logical pixels: height 32–160, icon size 16–64; default
height 56 and icon size 32. Canonical height is never below icon size + 16.
`taskbar_settings.values()` and `configure()` are RAM-only; a service timer
submits isolated `taskbar_settings_load` / `taskbar_settings_save` jobs. The worker
uses the desktop layout's OS save lock, fsync and atomic replace, keeps the last
valid backup, and rejects old/conflicting revisions. Rapid UI edits are coalesced,
including edits made while load or save is already running. Drawing never performs
file I/O or starts a process.

`AppBarController.reconcile({device: fresh_TASKBAR_Window}, monitor_snapshot,
height_logical)` registers only exact BLUI-owned no-activate taskbar HWNDs and
returns `{device: approved_physical_rect}`. Monitor DPI is applied here; root adds
the user's UI multiplier to logical height before the call. Negative monitor
origins remain physical desktop coordinates. The system query honors the existing
Windows taskbar and other AppBars. No global `SPI_SETWORKAREA`, registry edit,
foreign-window resize or maximize operation is used.

The root owner places each taskbar using the **approved** rectangle and validates
against physical monitor bounds (not its already-reduced work area). The native
WndProc sends ABM_WINDOWPOSCHANGED after movement, without a duplicate Python
notification. `CALLBACK_MESSAGE = 0x82A7` identifies
AppBar notifications in the native WndProc; ABN_POSCHANGED must trigger reconcile.
Native handling should also honor fullscreen-app z-order notifications and
re-register after the Windows Shell's TaskbarCreated message. Unchanged rectangles
do not send SETPOS again, avoiding notification loops.

The native taskbar-only GHOST WndProc subclass now handles those notifications.
It checks an owned HWND marker, sets pointer-sized generation/restart properties,
lowers only its own taskbar while a fullscreen app is present and restores it
without activation when fullscreen exits. It never recursively queries/sets the
AppBar from its notification callback. `notification_state(window)` reads the
generation/restart/fullscreen flags from a freshly validated Window;
`is_fullscreen(window)` lets root skip unconditional topmost promotion. Reconcile
detects a restart epoch and sends NEW again before restoring the reservation.
Per-registration tokens prevent same-process HWND/RNA reuse from unregistering
the new owner. Destruction has an additional native unregister fallback.
Reconcile caches the full-monitor geometry/work rectangle, logical height, exact window
identity and native generation/restart/fullscreen state: unchanged passes do not
send even a QUERYPOS IPC to Explorer. A native notification or setting/topology
change invalidates the cache, then the post-SETPOS generation is remembered to
prevent a self-notification loop.

Close the controller's registration **before** destroying its taskbar HWND, on
display removal, load and addon unregister. `close_window`, `close` and process
atexit cleanup revalidate PID/thread/start/class before ABM_REMOVE; a reused HWND
is never unregistered from its new owner. Unexpected destruction is also cleaned
by Windows. `snapshot()` is RAM-only. Only trusted system `shell32.dll` is loaded
with `LOAD_LIBRARY_SEARCH_SYSTEM32`; this path does not enumerate or load any
third-party context-menu extension.

Explicitly hiding the original Windows taskbar now coordinates its reservation
through the isolated visibility guard, following ManagedShell's temporary
`ABM_SETSTATE` AUTOHIDE approach (not copied code). Before changing anything,
separate atomic journals remember originally visible bars and the original
auto-hide bit. Only the fresh verified Explorer primary taskbar can change that
bit; existing auto-hide is never disabled on restoration. The guard preserves
current other state bits, relinquishes hiding after an external auto-hide change,
and both primary and crash-recovery guardians restore the transaction even when
no visibility hide occurred yet. Explorer replacement identities are journalled
before any new write. Other AppBars are never unregistered or manually resized;
Windows remains responsible for their reservations. No SPI work-area write is used.
Native ABN_STATECHANGE notifications, a changed monitor work rectangle, or
RAM-only `AppBarController.invalidate()` trigger re-query from the **full** monitor
rectangle, never from the already-reserved work area. This avoids double deduction.
The guard status exposes `reservation_reclaimed`, `reservation_pending`, and
`reservation_error`; pending recovery retains its journal for the next guard.
Multiple BLUI processes also get separate standard Windows AppBar reservations;
there is no global cross-process single-bar ownership yet.

Primary API contracts:

- [Using Application Desktop Toolbars](https://learn.microsoft.com/en-us/windows/win32/shell/application-desktop-toolbars):
  registration, two-step approved placement, notifications and cleanup.
- [SHAppBarMessage](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shappbarmessage):
  supported messages and message-dependent return values.
- [ABM_NEW](https://learn.microsoft.com/en-us/windows/win32/shell/abm-new),
  [ABM_QUERYPOS](https://learn.microsoft.com/en-us/windows/win32/shell/abm-querypos),
  [ABM_SETPOS](https://learn.microsoft.com/en-us/windows/win32/shell/abm-setpos),
  [ABM_REMOVE](https://learn.microsoft.com/en-us/windows/win32/shell/abm-remove).
- [ABM_GETSTATE](https://learn.microsoft.com/en-us/windows/win32/shell/abm-getstate),
  [ABM_SETSTATE](https://learn.microsoft.com/en-us/windows/win32/shell/abm-setstate):
  zero is a valid state, and SETSTATE's always-TRUE result requires GETSTATE readback.
- [ManagedShell ExplorerHelper](https://github.com/cairoshell/ManagedShell/blob/master/src/ManagedShell.AppBar/ExplorerHelper.cs):
  original taskbar auto-hide/reservation and visibility coordination reference.

Mock tests never register a real AppBar or alter the user's current work area.
Only root's owned native UI fixture may exercise a real registration and must
remove it immediately afterward.
`check_taskbar_reservation_native.py` is root-only serial QA: it temporarily hides
the real system taskbar through a fixture-owned guard, tests reclaimed AppBar
placement and explicit restoration, then terminates only that owned helper to
verify the second guardian. It restores original work areas/state/visibility and
keeps recovery journals if restoration cannot be confirmed.
