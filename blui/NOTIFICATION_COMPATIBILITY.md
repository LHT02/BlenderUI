# BLUI notification compatibility boundaries

## Implementation and ownership

All notification native calls and COM operations occur in the disposable helper.
Blender draw callbacks use validated RAM snapshots and existing preview IDs only.
The relay's message pump is separate from the historical UIAutomation thread, so
a faulty accessibility provider cannot block notification ADD/MODIFY/DELETE or UI.
Only the owner's exact process-creation identity keeps the helper alive.

The relay preserves the original Explorer receiver, forwards existing shell
messages with bounded timeouts, and restores registration broadcasts when it
exits. Private QA does not broadcast, forward to Explorer, bootstrap, or expose
system actions. Historical bootstrap does not require applications to register
again: it reads the original Explorer provider's existing UIA/COM state.

## Explicit capabilities

| Source | Display pixels | LEFT | RIGHT / DOUBLE / hover |
| --- | --- | --- | --- |
| Actual NIM callback captured by the relay | Copied HICON | Actual callback/version | Actual callback/version |
| Win10 original `ToolbarWindow32` button | Unique same-label COM HICON when available | Explorer original control | Explorer original control, guarded as below |
| UIA provider with Invoke/default action | Unique same-label COM HICON when available | Actual provider default action | Not synthesized; use original Windows area |
| Win10 COM item needing original overflow | Real HICON | Explicit click temporarily opens original overflow and fresh-locates the exact item | Same on-demand route for RIGHT/DOUBLE; no hidden callback guesses |
| ITrayNotify metadata only | Copied HICON if valid | Display only | Display only |

No callbackMessage/version is invented from ITrayNotify. Its NOTIFYITEM structure
does not contain either. Label matching only enriches presentation pixels; it does
not create callback identity or authorize another application action.

UIA tokens contain the verified original Explorer process creation identity and
RuntimeId. Controls must be in the actual notification subtree, not a desktop-wide
search or localized-name match. Invocation rechecks the original root, RuntimeId,
name, and capability. Cached COM element pointers are not reused across refreshes.

Win10 toolbar input also requires a real same-Explorer-process `ToolbarWindow32`
ancestor, an unchanged toolbar HWND/thread and full button rectangle, a nonambiguous
center, and complete containment in the toolbar client rectangle. Every message
rechecks root and toolbar identity and has a 250ms timeout. Only ordinary mouse
messages with scalar client coordinates are sent. No TB_GETBUTTON/TB_HITTEST local
pointer is sent across processes, no remote allocation/read/write is used, and
the physical pointer is never moved. This route is disabled for Windows11/XAML.

Win10 native evidence preserves Explorer's genuine event translation: LEFT can
be WM_LBUTTONDOWN+NIN_SELECT without WM_LBUTTONUP, RIGHT can be WM_RBUTTONDOWN,
DOUBLE can be WM_LBUTTONDBLCLK+NIN_SELECT, and hover-enter can be WM_MOUSEMOVE.
Hover-leave delivery clears the original toolbar hot item; Explorer does not
guarantee an application WM_MOUSELEAVE/NIN_POPUPCLOSE callback. BLUI neither
fabricates a missing callback nor claims this route equals direct NIM callbacks.

An automatically hidden icon may not expose a usable UIA rectangle or action. It
stays visible as display-only metadata if available and the UI offers restoration
of the original Windows notification area. The application does not silently
change auto-tray or icon preferences to make a test pass. On Windows10, an explicit
click on a nonempty-tooltip historical item may temporarily invoke the actual
original Chevron (Button/AutomationId/native ControlID1502 verified on build19045).
Before that, live App HWND+UID+GUID/process-creation identity and current COM
metadata must match. After expansion, only one fresh exact-tooltip Toolbar target
may be used; ambiguous/changed/missing items fail with the original-area fallback.
No direct callback/version is guessed. Only the exact dropdown opened by this
invocation is restored, and real user input changes prevent automatic closure.
An existing user-opened dropdown is never automatically closed.
RIGHT/DOUBLE never automatically toggle the dropdown closed, because the target
may open an app-owned menu/window. LEFT cleanup additionally requires the exact
post-expansion foreground HWND/creation identity to remain unchanged. Windows
focus changes handle natural closure; BLUI does not steal focus or dismiss the
application's requested popup.

## System controls and fallback behavior

Network, volume, power, input, notifications, calendar and original-area controls
use a fixed allowlist, separate from app callback identities. LEFT first attempts
the version-dependent actual scoped UIA control; RIGHT/DOUBLE use fixed settings
pages. The original-area UI button requests the existing crash-safe restore owner
and does not immediately focus a still-hidden Explorer bar.

When a scoped provider is absent, fixed fallbacks are explicit:

- Network: version-dependent network flyout URI, or documented network settings.
- Volume: Win11 quick settings (Win+A); Win10 Windows System32 `sndvol.exe`.
- Power: power settings (not a claimed equivalent battery flyout).
- Input: Win+Space switches input language (not a claimed persistent chooser).
- Notifications: Win11 Win+N; Win10 Win+A.
- Calendar: Win11 Win+N; Win10 Win+Alt+D.

Shortcuts refuse to run if physical modifier keys are already pressed and release
only keys they requested. No tooltip/search text becomes a URI, command, executable
path, callback ID, or arbitrary foreign HWND action. Known old Win11 system-icon
GUID callbacks use the fixed system-control route because upstream records crash
risks with the older callback implementations.

## Evidence and licensing

The development machine is Windows10 build 19045. Pure ABI/capability/mock tests
are not Windows11 end-to-end evidence. Do not claim full Windows11 compatibility
or real native Toolbar callback behavior until the respective root-run fixture
has passed. Unsupported providers produce a diagnostic status, not false success.

Root native evidence on Windows10 build19045: read-only bootstrap returned 24
items, all with real pixels (23 content-addressed digests), and an OWN original
Toolbar fixture passed actual LEFT/RIGHT/DOUBLE/hover-enter callbacks, honest
hover-leave delivery with no promised App callback, and OWN icon deletion.
The newer public on-demand OVERFLOW route has pure guarding evidence but has
not yet been tested end-to-end on an auto-hidden icon. Keep it explicitly PARTIAL.

Read-only root-run probe: `blui/tools/check_notification_bootstrap.py`.
OWN-only Win10 Explorer historical callback fixture:
`blui/tools/check_notification_history_native.py` (adds/removes only its unique
OWN icon; no relay, broadcasts, global preferences or other app callbacks).
Root read-only `check_notification_controls.py` records actual control identity;
it never invokes the Chevron or another control.
Existing `check_notification_host.py` / `check_notification_ui_native.py` are
private relay/Blender render fixtures and do not prove historical Win11 support.

Primary design/ABI references; implementation is independent, not copied/linked:

- [ManagedShell ExplorerTrayService](https://github.com/cairoshell/ManagedShell/blob/master/src/ManagedShell.WindowsTray/ExplorerTrayService.cs): upstream historical implementation uses legacy Toolbar and temporary auto-tray changes; BLUI deliberately does not use those global settings or remote-memory operations.
- [ManagedShell TrayNotify COM declarations](https://github.com/cairoshell/ManagedShell/blob/master/src/ManagedShell.WindowsTray/TrayNotify.cs): optional undocumented metadata ABI, checked at runtime.
- [ManagedShell NotifyIcon](https://github.com/cairoshell/ManagedShell/blob/master/src/ManagedShell.WindowsTray/NotifyIcon.cs): real notification versions, hover and version-specific system click caveats.
- [ManagedShell ShellHelper](https://github.com/cairoshell/ManagedShell/blob/master/src/ManagedShell.Common/Helpers/ShellHelper.cs): upstream Windows quick-settings/notification shortcut routing.
- [RetroBar](https://github.com/dremin/RetroBar): current UI delegates notification behavior to ManagedShell. Both projects are Apache-2.0, not MIT ([ManagedShell license](https://github.com/cairoshell/ManagedShell/blob/master/LICENSE), [RetroBar license](https://github.com/dremin/RetroBar/blob/master/LICENSE)).
- [Microsoft IUIAutomation](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomation), [UIA obtaining elements](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-obtainingelements), and installed Windows SDK `UIAutomationClient.h`: COM ABI, runtime identities, scoped providers and patterns.
- [Microsoft toolbar controls](https://learn.microsoft.com/en-us/windows/win32/controls/toolbar-control-reference), [NM_RCLICK](https://learn.microsoft.com/en-us/windows/win32/controls/nm-rclick-toolbar), [NM_DBLCLK](https://learn.microsoft.com/en-us/windows/win32/controls/nm-dblclk-toolbar), [mouse input](https://learn.microsoft.com/en-us/windows/win32/inputdev/about-mouse-input): original Common Controls mouse semantics; Explorer-specific forwarding still requires native evidence.
- [Shell_NotifyIcon](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw), [NOTIFYICONDATA](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw), [Windows shortcuts](https://support.microsoft.com/en-us/accessibility/windows/keyboard-shortcuts-in-windows), [launch settings](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings): public callback and fixed entry-point contracts.
