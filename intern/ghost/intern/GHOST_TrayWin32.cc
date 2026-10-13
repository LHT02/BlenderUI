/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/** \file
 * \ingroup GHOST
 *
 * Windows system tray icon. See GHOST_TrayWin32.hh for why this exists.
 */

#include "GHOST_TrayWin32.hh"
#include "GHOST_TrayMenuWin32.hh"

#ifdef _WIN32

#  include <cstdlib>
#  include <cstring>
#  include <string>
#  include <vector>

#  include <windows.h>
#  include <shellapi.h>

namespace {

const wchar_t *kWindowClass = L"BLUI_TrayWindow";

/* Custom message the shell sends when the icon is clicked. */
const UINT kTrayCallbackMessage = WM_APP + 1;

/* Native menu ids are stable, one-based indices into the label/command vectors. */
const UINT kFirstCommandId = 1;

bool utf8_to_utf16(const char *src, std::wstring &r_dst)
{
  if (src == nullptr) {
    r_dst.clear();
    return true;
  }
  const int len = MultiByteToWideChar(CP_UTF8, 0, src, -1, nullptr, 0);
  if (len <= 0) {
    return false;
  }
  std::vector<wchar_t> buffer;
  buffer.resize(size_t(len));
  if (MultiByteToWideChar(CP_UTF8, 0, src, -1, buffer.data(), len) != len) {
    return false;
  }
  r_dst.assign(buffer.data(), size_t(len - 1));
  return true;
}

class TrayIcon {
 public:
  bool add(const char *tooltip, const GHOST_TrayItem *items, int item_count);
  void remove();

  bool is_active() const { return m_added; }

  void set_handler(GHOST_TrayCommandFn handler, void *user_data)
  {
    m_handler = handler;
    m_user_data = user_data;
  }

 private:
  static LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);
  LRESULT handle_message(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);

  void show_menu(HWND hwnd);
  void run_command(size_t index);

  bool ensure_window_class();
  bool ensure_window();
  void refresh_icon();
  bool notify_add();

  HWND m_hwnd = nullptr;
  NOTIFYICONDATAW m_nid = {};
  bool m_added = false;
  HICON m_icon = nullptr;
  GHOST_TrayMenuWin32 *m_menu = nullptr;
  const UINT m_taskbar_created = RegisterWindowMessageW(L"TaskbarCreated");

  std::vector<std::wstring> m_labels;
  std::vector<std::string> m_commands;

  GHOST_TrayCommandFn m_handler = nullptr;
  void *m_user_data = nullptr;
};

TrayIcon g_tray;

bool TrayIcon::ensure_window_class()
{
  static bool registered = false;
  if (registered) {
    return true;
  }

  WNDCLASSEXW wc = {};
  wc.cbSize = sizeof(wc);
  wc.lpfnWndProc = &TrayIcon::window_proc;
  wc.hInstance = GetModuleHandleW(nullptr);
  wc.lpszClassName = kWindowClass;

  if (RegisterClassExW(&wc) == 0) {
    /* Already registered by an earlier call in this process. */
    if (GetLastError() != ERROR_CLASS_ALREADY_EXISTS) {
      return false;
    }
  }
  registered = true;
  return true;
}

bool TrayIcon::ensure_window()
{
  if (m_hwnd != nullptr) {
    return true;
  }
  if (!ensure_window_class()) {
    return false;
  }

  /* A plain hidden top-level window rather than a message-only one: the shell
   * is documented to work with the former, and message-only windows have a
   * history of the icon never appearing. */
  m_hwnd = CreateWindowExW(0,
                           kWindowClass,
                           L"BLUI tray",
                           WS_OVERLAPPED,
                           0,
                           0,
                           0,
                           0,
                           nullptr,
                           nullptr,
                           GetModuleHandleW(nullptr),
                           this);
  return m_hwnd != nullptr;
}

LRESULT CALLBACK TrayIcon::window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
  TrayIcon *self = nullptr;

  if (message == WM_NCCREATE) {
    CREATESTRUCTW *create = reinterpret_cast<CREATESTRUCTW *>(lparam);
    self = static_cast<TrayIcon *>(create->lpCreateParams);
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
  }
  else {
    self = reinterpret_cast<TrayIcon *>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
  }

  if (self != nullptr) {
    return self->handle_message(hwnd, message, wparam, lparam);
  }
  return DefWindowProcW(hwnd, message, wparam, lparam);
}

LRESULT TrayIcon::handle_message(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
  if (m_taskbar_created != 0 && message == m_taskbar_created) {
    /* Explorer can restart without our windows closing. Preserve the logical active state
     * until the shell has accepted the replacement icon. */
    if (m_added) {
      refresh_icon();
      notify_add();
    }
    return 0;
  }
  switch (message) {
    case kTrayCallbackMessage: {
      switch (LOWORD(lparam)) {
        case WM_LBUTTONUP:
        case NIN_SELECT:
        case NIN_KEYSELECT:
          /* Left click runs the first real entry, which the caller makes the
           * most useful one. */
          for (size_t i = 0; i < m_commands.size(); i++) {
            if (!m_commands[i].empty()) {
              run_command(i);
              break;
            }
          }
          return 0;
        case WM_RBUTTONUP:
        case WM_CONTEXTMENU:
          show_menu(hwnd);
          return 0;
        default:
          break;
      }
      return 0;
    }
    case WM_MEASUREITEM:
      if (m_menu && lparam && m_menu->measure(*reinterpret_cast<MEASUREITEMSTRUCT *>(lparam))) {
        return TRUE;
      }
      break;
    case WM_DRAWITEM:
      if (m_menu && lparam && m_menu->draw(*reinterpret_cast<DRAWITEMSTRUCT *>(lparam))) {
        return TRUE;
      }
      break;
    case WM_SETTINGCHANGE:
    case WM_THEMECHANGED:
    case WM_SYSCOLORCHANGE:
    case WM_DWMCOLORIZATIONCOLORCHANGED:
    case WM_DISPLAYCHANGE:
      if (m_menu) {
        EndMenu();
      }
      if (m_added) {
        refresh_icon();
      }
      return 0;
    case WM_DESTROY:
      remove();
      return 0;
    default:
      break;
  }
  return DefWindowProcW(hwnd, message, wparam, lparam);
}

void TrayIcon::show_menu(HWND hwnd)
{
  if (m_menu) {
    return;
  }
  GHOST_TrayMenuWin32 menu(hwnd, m_labels);
  m_menu = &menu;
  const int chosen = menu.show(hwnd);
  m_menu = nullptr;
  if (chosen >= int(kFirstCommandId)) {
    run_command(size_t(chosen - kFirstCommandId));
  }
}

void TrayIcon::run_command(size_t index)
{
  if (m_handler == nullptr || index >= m_commands.size() || m_commands[index].empty()) {
    return;
  }
  m_handler(m_commands[index].c_str(), m_user_data);
}

bool TrayIcon::add(const char *tooltip, const GHOST_TrayItem *items, int item_count)
{
  remove();

  if (items == nullptr || item_count <= 0) {
    return false;
  }

  m_labels.clear();
  m_commands.clear();
  for (int i = 0; i < item_count; i++) {
    std::wstring label;
    if (!utf8_to_utf16(items[i].label, label)) {
      return false;
    }
    m_labels.push_back(std::move(label));
    m_commands.emplace_back(items[i].command != nullptr ? items[i].command : "");
  }

  if (!ensure_window()) {
    return false;
  }

  std::wstring wide_tooltip;
  utf8_to_utf16(tooltip, wide_tooltip);

  m_nid = {};
  m_nid.cbSize = sizeof(m_nid);
  m_nid.hWnd = m_hwnd;
  m_nid.uID = 1;
  m_nid.uFlags = NIF_MESSAGE | NIF_TIP | NIF_ICON | NIF_SHOWTIP;
  m_nid.uCallbackMessage = kTrayCallbackMessage;
  refresh_icon();
  /* szTip is a fixed array, so truncation is the only failure mode. */
  wcsncpy(m_nid.szTip, wide_tooltip.c_str(), ARRAYSIZE(m_nid.szTip) - 1);

  m_added = notify_add();
  return m_added;
}

bool TrayIcon::notify_add()
{
  if (!Shell_NotifyIconW(NIM_ADD, &m_nid)) {
    return false;
  }
  /* Required after every NIM_ADD, including shell restarts. Version 4 preserves the
   * documented keyboard activation and callback coordinates. */
  m_nid.uVersion = NOTIFYICON_VERSION_4;
  Shell_NotifyIconW(NIM_SETVERSION, &m_nid);
  return true;
}

void TrayIcon::refresh_icon()
{
  /* APPICON is a named application resource. Numeric 1 is the .blend file icon. Keep the
   * application's brand colors; menu contrast belongs to the native shell palette. */
  using MetricsForDpi = int(WINAPI *)(int, UINT);
  const HMODULE user32 = GetModuleHandleW(L"user32.dll");
  const auto metrics_for_dpi = reinterpret_cast<MetricsForDpi>(
      GetProcAddress(user32, "GetSystemMetricsForDpi"));
  const UINT dpi = GHOST_ThemeWin32_MenuDpi(m_hwnd);
  const int width = metrics_for_dpi ? metrics_for_dpi(SM_CXSMICON, dpi) : GetSystemMetrics(SM_CXSMICON);
  const int height = metrics_for_dpi ? metrics_for_dpi(SM_CYSMICON, dpi) : GetSystemMetrics(SM_CYSMICON);
  HICON icon = static_cast<HICON>(
      LoadImageW(GetModuleHandleW(nullptr), L"APPICON", IMAGE_ICON, width, height, LR_DEFAULTCOLOR));
  if (!icon) {
    icon = static_cast<HICON>(LoadImageW(nullptr,
                                       MAKEINTRESOURCEW(32512), /* IDI_APPLICATION, explicitly UTF-16. */
                                       IMAGE_ICON,
                                       width,
                                       height,
                                       LR_DEFAULTCOLOR));
  }
  if (!icon) {
    return;
  }
  const HICON previous = m_icon;
  m_icon = icon;
  m_nid.hIcon = m_icon;
  if (m_added) {
    NOTIFYICONDATAW update = m_nid;
    update.uFlags = NIF_ICON;
    Shell_NotifyIconW(NIM_MODIFY, &update);
  }
  if (previous) {
    DestroyIcon(previous);
  }
}

void TrayIcon::remove()
{
  if (m_menu) {
    EndMenu();
  }
  if (m_added) {
    Shell_NotifyIconW(NIM_DELETE, &m_nid);
  }
  m_added = false;
  if (m_icon) {
    DestroyIcon(m_icon);
    m_icon = nullptr;
    m_nid.hIcon = nullptr;
  }
}

}  // namespace

bool GHOST_TrayWin32_Add(const char *tooltip, const GHOST_TrayItem *items, int item_count)
{
  return g_tray.add(tooltip, items, item_count);
}

void GHOST_TrayWin32_Remove(void)
{
  g_tray.remove();
}

bool GHOST_TrayWin32_IsActive(void)
{
  return g_tray.is_active();
}

void GHOST_TrayWin32_SetCommandHandler(GHOST_TrayCommandFn handler, void *user_data)
{
  g_tray.set_handler(handler, user_data);
}

#endif /* _WIN32 */
