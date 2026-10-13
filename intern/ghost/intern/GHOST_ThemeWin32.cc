/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2026 BLUI */

#include "GHOST_ThemeWin32.hh"

#ifdef _WIN32
#  include <dwmapi.h>
#  include <shellscalingapi.h>

namespace {

COLORREF blend(COLORREF background, COLORREF foreground, int weight)
{
  return RGB((GetRValue(background) * (100 - weight) + GetRValue(foreground) * weight) / 100,
             (GetGValue(background) * (100 - weight) + GetGValue(foreground) * weight) / 100,
             (GetBValue(background) * (100 - weight) + GetBValue(foreground) * weight) / 100);
}

bool is_dark(bool shell)
{
  DWORD light = 1;
  DWORD size = sizeof(light);
  const LONG result = RegGetValueW(
      HKEY_CURRENT_USER,
      L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
      shell ? L"SystemUsesLightTheme" : L"AppsUseLightTheme",
      RRF_RT_REG_DWORD,
      nullptr,
      &light,
      &size);
  if (result == ERROR_SUCCESS) {
    return light == 0;
  }
  const COLORREF color = GetSysColor(COLOR_WINDOW);
  return GetRValue(color) * 299 + GetGValue(color) * 587 + GetBValue(color) * 114 < 128000;
}

}  // namespace

GHOST_ThemePaletteWin32 GHOST_ThemeWin32_Palette(bool shell)
{
  HIGHCONTRASTW contrast = {sizeof(contrast)};
  const bool high_contrast = SystemParametersInfoW(
                                 SPI_GETHIGHCONTRAST, sizeof(contrast), &contrast, 0) &&
                             (contrast.dwFlags & HCF_HIGHCONTRASTON);
  GHOST_ThemePaletteWin32 palette = {};
  palette.dark = is_dark(shell);
  palette.high_contrast = high_contrast;
  if (high_contrast) {
    palette.background = GetSysColor(COLOR_MENU);
    palette.text = GetSysColor(COLOR_MENUTEXT);
    palette.disabled_text = GetSysColor(COLOR_GRAYTEXT);
    palette.selected_background = GetSysColor(COLOR_HIGHLIGHT);
    palette.selected_text = GetSysColor(COLOR_HIGHLIGHTTEXT);
    palette.separator = GetSysColor(COLOR_MENUTEXT);
    return palette;
  }

  palette.background = palette.dark ? RGB(32, 32, 32) : RGB(243, 243, 243);
  palette.text = palette.dark ? RGB(245, 245, 245) : RGB(26, 26, 26);
  palette.disabled_text = palette.dark ? RGB(156, 156, 156) : RGB(120, 120, 120);
  palette.separator = palette.dark ? RGB(69, 69, 69) : RGB(210, 210, 210);
  DWORD accent;
  BOOL opaque;
  COLORREF highlight = GetSysColor(COLOR_HIGHLIGHT);
  if (SUCCEEDED(DwmGetColorizationColor(&accent, &opaque))) {
    highlight = RGB((accent >> 16) & 255, (accent >> 8) & 255, accent & 255);
  }
  palette.selected_background = blend(palette.background, highlight, palette.dark ? 35 : 20);
  palette.selected_text = palette.text;
  return palette;
}

UINT GHOST_ThemeWin32_MenuDpi(HWND fallback)
{
  POINT pointer;
  UINT dpi_x = 96, dpi_y = 96;
  const HMONITOR monitor = GetCursorPos(&pointer) ?
                               MonitorFromPoint(pointer, MONITOR_DEFAULTTONEAREST) :
                               MonitorFromWindow(fallback, MONITOR_DEFAULTTONEAREST);
  if (SUCCEEDED(GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, &dpi_x, &dpi_y))) {
    return dpi_x;
  }
  return 96;
}

HFONT GHOST_ThemeWin32_MenuFont(UINT dpi)
{
  NONCLIENTMETRICSW metrics = {sizeof(metrics)};
  using ParametersForDpi = BOOL(WINAPI *)(UINT, UINT, PVOID, UINT, UINT);
  const HMODULE user32 = GetModuleHandleW(L"user32.dll");
  const auto for_dpi = reinterpret_cast<ParametersForDpi>(
      GetProcAddress(user32, "SystemParametersInfoForDpi"));
  if (for_dpi && for_dpi(SPI_GETNONCLIENTMETRICS, sizeof(metrics), &metrics, 0, dpi)) {
    return CreateFontIndirectW(&metrics.lfMenuFont);
  }
  if (!SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof(metrics), &metrics, 0)) {
    return nullptr;
  }
  HDC desktop = GetDC(nullptr);
  const int system_dpi = desktop ? GetDeviceCaps(desktop, LOGPIXELSY) : 96;
  if (desktop) {
    ReleaseDC(nullptr, desktop);
  }
  metrics.lfMenuFont.lfHeight = MulDiv(metrics.lfMenuFont.lfHeight, dpi, system_dpi);
  return CreateFontIndirectW(&metrics.lfMenuFont);
}
#endif
