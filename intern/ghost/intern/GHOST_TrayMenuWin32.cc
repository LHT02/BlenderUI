/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2026 BLUI */

#include "GHOST_TrayMenuWin32.hh"

#ifdef _WIN32

int GHOST_TrayMenuWin32::scaled(int pixels) const
{
  return MulDiv(pixels, dpi_, 96);
}

GHOST_TrayMenuWin32::GHOST_TrayMenuWin32(HWND owner, const std::vector<std::wstring> &labels)
    : labels_(labels),
      palette_(GHOST_ThemeWin32_Palette(true)),
      dpi_(GHOST_ThemeWin32_MenuDpi(owner))
{
  menu_ = CreatePopupMenu();
  if (!menu_) {
    return;
  }
  font_ = GHOST_ThemeWin32_MenuFont(dpi_);
  background_ = CreateSolidBrush(palette_.background);
  MENUINFO info = {sizeof(info)};
  info.fMask = MIM_BACKGROUND;
  info.hbrBack = background_;
  SetMenuInfo(menu_, &info);

  HDC dc = GetDC(owner);
  if (dc) {
    const HGDIOBJ previous = SelectObject(dc, font_ ? font_ : GetStockObject(DEFAULT_GUI_FONT));
    TEXTMETRICW metrics;
    if (GetTextMetricsW(dc, &metrics)) {
      row_height_ = UINT(metrics.tmHeight + scaled(16));
    }
    for (const std::wstring &label : labels_) {
      SIZE size;
      if (GetTextExtentPoint32W(dc, label.c_str(), int(label.size()), &size) &&
          UINT(size.cx) > width_)
      {
        width_ = UINT(size.cx);
      }
    }
    SelectObject(dc, previous);
    ReleaseDC(owner, dc);
  }
  if (!row_height_) {
    row_height_ = UINT(scaled(32));
  }
  width_ += UINT(scaled(44));
  if (width_ < UINT(scaled(180))) {
    width_ = UINT(scaled(180));
  }

  /* Stable vector indices are easier to validate than arbitrary item-data pointers. The UTF-16
   * string stays attached for native menu accessibility and keyboard handling. */
  for (size_t i = 0; i < labels_.size(); i++) {
    MENUITEMINFOW item = {sizeof(item)};
    item.fMask = MIIM_FTYPE | MIIM_ID | MIIM_DATA | MIIM_STRING;
    item.fType = MFT_OWNERDRAW;
    item.wID = UINT(i + 1);
    item.dwItemData = ULONG_PTR(i + 1);
    item.dwTypeData = const_cast<wchar_t *>(labels_[i].c_str());
    if (labels_[i].empty()) {
      item.fType |= MFT_SEPARATOR;
    }
    InsertMenuItemW(menu_, UINT(i), TRUE, &item);
  }
}

GHOST_TrayMenuWin32::~GHOST_TrayMenuWin32()
{
  if (menu_) {
    DestroyMenu(menu_);
  }
  if (background_) {
    DeleteObject(background_);
  }
  if (font_) {
    DeleteObject(font_);
  }
}

bool GHOST_TrayMenuWin32::measure(MEASUREITEMSTRUCT &item) const
{
  if (item.CtlType != ODT_MENU || item.itemData < 1 || item.itemData > labels_.size()) {
    return false;
  }
  item.itemWidth = width_;
  item.itemHeight = labels_[item.itemData - 1].empty() ? UINT(scaled(10)) : row_height_;
  return true;
}

bool GHOST_TrayMenuWin32::draw(const DRAWITEMSTRUCT &item) const
{
  if (item.CtlType != ODT_MENU || item.itemData < 1 || item.itemData > labels_.size()) {
    return false;
  }
  const std::wstring &label = labels_[item.itemData - 1];
  const bool disabled = (item.itemState & (ODS_DISABLED | ODS_GRAYED)) != 0;
  const bool selected = (item.itemState & ODS_SELECTED) != 0 && !label.empty() && !disabled;
  HBRUSH brush = CreateSolidBrush(selected ? palette_.selected_background : palette_.background);
  FillRect(item.hDC, &item.rcItem, brush);
  DeleteObject(brush);
  if (label.empty()) {
    RECT line = item.rcItem;
    line.left += scaled(12);
    line.right -= scaled(12);
    line.top = (line.top + line.bottom) / 2;
    line.bottom = line.top + 1;
    brush = CreateSolidBrush(palette_.separator);
    FillRect(item.hDC, &line, brush);
    DeleteObject(brush);
    return true;
  }
  const int saved = SaveDC(item.hDC);
  SelectObject(item.hDC, font_ ? font_ : GetStockObject(DEFAULT_GUI_FONT));
  SetBkMode(item.hDC, TRANSPARENT);
  SetTextColor(item.hDC,
               disabled ? palette_.disabled_text :
                          (selected ? palette_.selected_text : palette_.text));
  RECT text_rect = item.rcItem;
  text_rect.left += scaled(20);
  text_rect.right -= scaled(20);
  DrawTextW(item.hDC,
            label.c_str(),
            int(label.size()),
            &text_rect,
            DT_SINGLELINE | DT_VCENTER | DT_LEFT |
                ((item.itemState & ODS_NOACCEL) ? DT_HIDEPREFIX : 0));
  if (palette_.high_contrast && (item.itemState & ODS_FOCUS)) {
    DrawFocusRect(item.hDC, &item.rcItem);
  }
  RestoreDC(item.hDC, saved);
  return true;
}

int GHOST_TrayMenuWin32::show(HWND owner) const
{
  if (!menu_) {
    return 0;
  }
  POINT pointer;
  if (!GetCursorPos(&pointer)) {
    return 0;
  }
  SetForegroundWindow(owner);
  const int chosen = int(TrackPopupMenu(
      menu_, TPM_RETURNCMD | TPM_RIGHTBUTTON, pointer.x, pointer.y, 0, owner, nullptr));
  PostMessageW(owner, WM_NULL, 0, 0);
  return chosen;
}
#endif
