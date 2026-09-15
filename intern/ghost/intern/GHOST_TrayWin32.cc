/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/** \file
 * \ingroup GHOST
 *
 * Windows system tray icon. See GHOST_TrayWin32.hh for why this exists.
 */

#include "GHOST_TrayWin32.hh"

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

/* Ids handed to TrackPopupMenu. Separators do not consume one. */
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

  HWND m_hwnd = nullptr;
  NOTIFYICONDATAW m_nid = {};
  bool m_added = false;

  std::vector<std::wstring> m_labels;
  std::vector<std::string> m_commands;
  /* Menu id -> index into m_commands, or -1 for a separator. */
  std::vector<int> m_id_to_command;

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
  switch (message) {
    case kTrayCallbackMessage: {
      switch (LOWORD(lparam)) {
        case WM_LBUTTONUP:
          /* Left click runs the first real entry, which the caller makes the
           * most useful one. */
          for (size_t i = 0; i < m_id_to_command.size(); i++) {
            if (m_id_to_command[i] >= 0) {
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
  HMENU menu = CreatePopupMenu();
  if (menu == nullptr) {
    return;
  }

  m_id_to_command.assign(m_labels.size(), -1);

  UINT next_id = kFirstCommandId;
  for (size_t i = 0; i < m_labels.size(); i++) {
    if (m_labels[i].empty()) {
      AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
      continue;
    }
    AppendMenuW(menu, MF_STRING, next_id, m_labels[i].c_str());
    m_id_to_command[i] = int(next_id);
    next_id++;
  }

  POINT cursor;
  GetCursorPos(&cursor);

  /* Both of these are required for the menu to dismiss when the user clicks
   * elsewhere - the shell only routes the dismissal to the foreground window. */
  SetForegroundWindow(hwnd);
  const int chosen = int(TrackPopupMenu(menu,
                                        TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                        cursor.x,
                                        cursor.y,
                                        0,
                                        hwnd,
                                        nullptr));
  PostMessageW(hwnd, WM_NULL, 0, 0);
  DestroyMenu(menu);

  if (chosen < int(kFirstCommandId)) {
    return;
  }
  const UINT id = UINT(chosen);
  for (size_t i = 0; i < m_id_to_command.size(); i++) {
    if (m_id_to_command[i] == int(id)) {
      run_command(i);
      return;
    }
  }
}

void TrayIcon::run_command(size_t index)
{
  if (m_handler == nullptr || index >= m_commands.size()) {
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
  m_nid.uFlags = NIF_MESSAGE | NIF_TIP | NIF_ICON;
  m_nid.uCallbackMessage = kTrayCallbackMessage;
  /* Icon 1 is the application icon from the resource script. */
  m_nid.hIcon = LoadIconW(GetModuleHandleW(nullptr),
                          reinterpret_cast<LPCWSTR>(MAKEINTRESOURCEW(1)));
  if (m_nid.hIcon == nullptr) {
    m_nid.hIcon = LoadIconW(nullptr, reinterpret_cast<LPCWSTR>(IDI_APPLICATION));
  }
  /* szTip is a fixed array, so truncation is the only failure mode. */
  wcsncpy(m_nid.szTip, wide_tooltip.c_str(), ARRAYSIZE(m_nid.szTip) - 1);

  m_added = Shell_NotifyIconW(NIM_ADD, &m_nid) != FALSE;
  return m_added;
}

void TrayIcon::remove()
{
  if (!m_added) {
    return;
  }
  Shell_NotifyIconW(NIM_DELETE, &m_nid);
  m_added = false;
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
