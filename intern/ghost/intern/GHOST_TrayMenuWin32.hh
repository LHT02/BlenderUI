/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2026 BLUI */

#pragma once

#ifdef _WIN32
#  include "GHOST_ThemeWin32.hh"
#  include <string>
#  include <vector>

/** Native popup with explicit documented owner drawing, not private uxtheme ordinals. */
class GHOST_TrayMenuWin32 {
 public:
  GHOST_TrayMenuWin32(HWND owner, const std::vector<std::wstring> &labels);
  ~GHOST_TrayMenuWin32();

  bool measure(MEASUREITEMSTRUCT &item) const;
  bool draw(const DRAWITEMSTRUCT &item) const;
  int show(HWND owner) const;

 private:
  HMENU menu_ = nullptr;
  HBRUSH background_ = nullptr;
  HFONT font_ = nullptr;
  const std::vector<std::wstring> &labels_;
  GHOST_ThemePaletteWin32 palette_;
  UINT dpi_;
  UINT width_ = 0;
  UINT row_height_ = 0;
  int scaled(int pixels) const;
};
#endif
