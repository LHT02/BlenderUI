# Taskbar live window previews

The shell hover controller owns a separate top-level preview popup above the
taskbar. It calls `PreviewController.update(window, tasks, rects,
excluded=live_shell_handles)` from its service timer, never from UI drawing.
Rects use physical pixels relative to the popup's top-left client origin.
`preview_layout(count, available_width, scale=effective_dpi_scale)` returns
up to four bounded cards; the popup's native size must match that geometry.
The drawing code only reads `controller.snapshot()` and renders the title and
the fallback label. `LIVE` card contents are composited directly by Windows DWM.

This is not screenshot capture: no pixel buffer, disk thumbnail, upload or
export is created. No Shell extension is loaded into the UI. Only the trusted
system `dwmapi.dll` is loaded, with `LOAD_LIBRARY_SEARCH_SYSTEM32`.

The controller validates exact HWND/PID/thread/process-start/window-class
identities before registration and again before compositing. The destination
must be an owned `GHOST_WindowClass` top-level popup, not the thin taskbar or
a foreign HWND. Sources exclude all shell helper windows; invisible, cloaked,
minimized, changed and explicitly protected windows get placeholders. DWM
failures never restore, activate, resize or otherwise alter the source app.

The shell owner must call `close()` before closing/replacing its popup and on
load, undo/redo, addon unregister and lifecycle reset. `close_all()` is also
registered with `atexit`; destroyed sources are removed on the next timer pass.
Every retained registration belongs to the current process and is unregistered
there. Mock-only regression tests never examine or modify real foreign windows.

API contracts were checked against primary Microsoft documentation:

- [DwmRegisterThumbnail](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmregisterthumbnail)
  requires top-level windows and a destination owned by the calling process.
- [DwmUpdateThumbnailProperties](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmupdatethumbnailproperties)
  is required before the new relationship becomes visible.
- [DWM_THUMBNAIL_PROPERTIES](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ns-dwmapi-dwm_thumbnail_properties)
  defines client-relative destination, visibility, opacity and source selection.
- [DwmUnregisterThumbnail](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmunregisterthumbnail)
  must run in the process that registered the thumbnail.
- [GetWindowDisplayAffinity](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowdisplayaffinity)
  reports an app's explicit content-protection setting when supported.
