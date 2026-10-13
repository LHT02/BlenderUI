/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2026 BLUI */

#pragma once

#ifdef _WIN32
#  include <windows.h>

/** Native shell colors. These must not replace the user's Blender UI theme. */
struct GHOST_ThemePaletteWin32 {
  bool dark;
  bool high_contrast;
  COLORREF background;
  COLORREF text;
  COLORREF disabled_text;
  COLORREF selected_background;
  COLORREF selected_text;
  COLORREF separator;
};

/** The tray follows the Windows shell preference; window frames follow the app preference. */
GHOST_ThemePaletteWin32 GHOST_ThemeWin32_Palette(bool shell);

/** Obtain the native menu font and scaling for the monitor under the pointer. */
UINT GHOST_ThemeWin32_MenuDpi(HWND fallback);
HFONT GHOST_ThemeWin32_MenuFont(UINT dpi);
#endif
