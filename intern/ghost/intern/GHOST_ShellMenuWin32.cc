/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/** \file
 * \ingroup GHOST
 *
 * Windows shell context menu. See GHOST_ShellMenuWin32.hh for why this exists.
 * Depends on the Windows SDK only, so the menu can be built and inspected
 * without a window - see blui/tools/shellmenu_selftest.cc.
 */

#include "GHOST_ShellMenuWin32.hh"

#ifdef _WIN32

#  include <cstdlib>
#  include <cstring>
#  include <string>
#  include <vector>

#  include <windows.h>
#  include <shlobj.h>
#  include <shlwapi.h>
#  include <winternl.h>

/**
 * True on Windows 11 (build 22000) and later.
 *
 * `GetVersionEx` reports whatever the executable's manifest declares rather
 * than the version actually running, so this asks ntdll for the real one - the
 * same route the shell itself takes.
 */
static bool windows_is_11_or_greater()
{
  using RtlGetVersionFn = LONG(WINAPI *)(PRTL_OSVERSIONINFOW);

  HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
  if (ntdll == nullptr) {
    return false;
  }
  auto rtl_get_version = reinterpret_cast<RtlGetVersionFn>(
      reinterpret_cast<void *>(GetProcAddress(ntdll, "RtlGetVersion")));
  if (rtl_get_version == nullptr) {
    return false;
  }

  RTL_OSVERSIONINFOW info = {};
  info.dwOSVersionInfoSize = sizeof(info);
  if (rtl_get_version(&info) != 0) {
    return false;
  }

  return info.dwMajorVersion > 10 || (info.dwMajorVersion == 10 && info.dwBuildNumber >= 22000);
}

/* -------------------------------------------------------------------- */
/** \name UTF conversion
 * \{ */

static bool utf8_to_utf16(const char *src, std::wstring &r_dst)
{
  if (src == nullptr) {
    return false;
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

static bool utf16_to_utf8(const wchar_t *src, char **r_dst)
{
  const int len = WideCharToMultiByte(CP_UTF8, 0, src, -1, nullptr, 0, nullptr, nullptr);
  if (len <= 0) {
    return false;
  }
  char *buffer = static_cast<char *>(malloc(size_t(len)));
  if (buffer == nullptr) {
    return false;
  }
  if (WideCharToMultiByte(CP_UTF8, 0, src, -1, buffer, len, nullptr, nullptr) != len) {
    free(buffer);
    return false;
  }
  *r_dst = buffer;
  return true;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Menu construction
 * \{ */

namespace {

/* Menu ids handed to the shell. It fills this range with its own commands. */
constexpr UINT kFirstId = 1;
constexpr UINT kLastId = 0x7FFF;

/**
 * Owns everything needed to build and invoke a shell menu for a set of files.
 */
class ShellMenu {
 public:
  ShellMenu() = default;
  ~ShellMenu() { destroy(); }

  ShellMenu(const ShellMenu &) = delete;
  ShellMenu &operator=(const ShellMenu &) = delete;

  bool build(const char *const *utf8_paths, int count);

  HMENU menu() const { return m_menu; }
  IContextMenu *context_menu() const { return m_context_menu; }

  /**
   * Forward a menu message to the shell's own handler.
   *
   * Shell extensions that draw their own items, or that fill a submenu only
   * when it opens, implement `IContextMenu2` or `IContextMenu3` and receive
   * their messages here. Without this the top-level entries still appear - they
   * come from `QueryContextMenu` - but every submenu an extension owns stays
   * empty, which is what 7-Zip's and TortoiseSVN's do.
   *
   * \return True if a handler took the message.
   */
  bool handle_menu_msg(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT *r_result);

  /** True if the shell's menu implements `IContextMenu2` or `IContextMenu3`. */
  bool has_menu_messages() const { return m_context_menu2 != nullptr; }

 private:
  void destroy();

  IShellFolder *m_folder = nullptr;
  IContextMenu *m_context_menu = nullptr;
  /* Aliases of `m_context_menu`, obtained by QueryInterface - releasing
   * `m_context_menu` covers all three. Only one of these is ever non-null:
   * `IContextMenu3` derives from `IContextMenu2`, so it is preferred. */
  IContextMenu2 *m_context_menu2 = nullptr;
  IContextMenu3 *m_context_menu3 = nullptr;
  HMENU m_menu = nullptr;
  /* Absolute item pidls; the child entries point into them. */
  std::vector<PIDLIST_ABSOLUTE> m_item_pidls;
  std::vector<PCUITEMID_CHILD> m_children;
};

bool ShellMenu::build(const char *const *utf8_paths, int count)
{
  if (utf8_paths == nullptr || count <= 0) {
    return false;
  }

  for (int i = 0; i < count; i++) {
    std::wstring wide;
    if (!utf8_to_utf16(utf8_paths[i], wide)) {
      return false;
    }
    PIDLIST_ABSOLUTE pidl = nullptr;
    if (FAILED(SHParseDisplayName(wide.c_str(), nullptr, &pidl, 0, nullptr)) || pidl == nullptr) {
      return false;
    }
    m_item_pidls.push_back(pidl);
  }

  /* A single shell menu can only act on items that share a parent folder, so
   * that is the set the menu is built for. */
  PIDLIST_ABSOLUTE first_parent = ILClone(m_item_pidls[0]);
  if (first_parent == nullptr) {
    return false;
  }
  ILRemoveLastID(first_parent);

  for (PIDLIST_ABSOLUTE pidl : m_item_pidls) {
    PIDLIST_ABSOLUTE parent = ILClone(pidl);
    if (parent == nullptr) {
      continue;
    }
    ILRemoveLastID(parent);
    const bool same_parent = ILIsEqual(parent, first_parent);
    ILFree(parent);
    if (same_parent) {
      m_children.push_back(ILFindLastID(pidl));
    }
  }
  ILFree(first_parent);

  if (m_children.empty()) {
    return false;
  }

  if (FAILED(SHBindToParent(m_item_pidls[0], IID_IShellFolder, (void **)&m_folder, nullptr)) ||
      m_folder == nullptr) {
    return false;
  }

  if (FAILED(m_folder->GetUIObjectOf(nullptr,
                                     UINT(m_children.size()),
                                     m_children.data(),
                                     IID_IContextMenu,
                                     nullptr,
                                     (void **)&m_context_menu)) ||
      m_context_menu == nullptr)
  {
    return false;
  }

  m_menu = CreatePopupMenu();
  if (m_menu == nullptr) {
    return false;
  }

  /* Ask the shell's menu object whether it wants its messages forwarded.
   *
   * This is what makes extension submenus work. `QueryContextMenu` produces the
   * top-level entries, so a menu that does not do this looks complete until the
   * user opens one - 7-Zip's and TortoiseSVN's then come up empty.
   * `IContextMenu3` derives from `IContextMenu2`, so it is tried first and used
   * for both. */
  if (FAILED(m_context_menu->QueryInterface(
          IID_IContextMenu3, reinterpret_cast<void **>(&m_context_menu3))))
  {
    m_context_menu3 = nullptr;
    if (FAILED(m_context_menu->QueryInterface(
            IID_IContextMenu2, reinterpret_cast<void **>(&m_context_menu2))))
    {
      m_context_menu2 = nullptr;
    }
  }
  else {
    /* Same object; `m_context_menu2` is an alias and must not be released. */
    m_context_menu2 = m_context_menu3;
  }

  /* CMF_EXTENDEDVERBS is what puts the entries Windows 11 keeps behind
   * "Show more options" into the menu. On Windows 10 there is no such split -
   * the normal right-click menu already is the extended one - and passing it
   * there adds the verbs that are otherwise reserved for Shift+right-click. */
  const UINT flags = CMF_NORMAL | (windows_is_11_or_greater() ? CMF_EXTENDEDVERBS : 0);

  const HRESULT result = m_context_menu->QueryContextMenu(m_menu, 0, kFirstId, kLastId, flags);
  if (FAILED(result)) {
    return false;
  }

  return GetMenuItemCount(m_menu) > 0;
}

bool ShellMenu::handle_menu_msg(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT *r_result)
{
  if (m_context_menu3 != nullptr) {
    *r_result = 0;
    return SUCCEEDED(m_context_menu3->HandleMenuMsg2(msg, wparam, lparam, r_result));
  }
  if (m_context_menu2 != nullptr) {
    return SUCCEEDED(m_context_menu2->HandleMenuMsg(msg, wparam, lparam));
  }
  return false;
}

void ShellMenu::destroy()
{
  if (m_menu != nullptr) {
    DestroyMenu(m_menu);
    m_menu = nullptr;
  }
  /* `m_context_menu2` aliases `m_context_menu3` when the latter exists, so only
   * one of them is released and it is released first. */
  if (m_context_menu3 != nullptr) {
    m_context_menu3->Release();
    m_context_menu3 = nullptr;
    m_context_menu2 = nullptr;
  }
  else if (m_context_menu2 != nullptr) {
    m_context_menu2->Release();
    m_context_menu2 = nullptr;
  }
  if (m_context_menu != nullptr) {
    m_context_menu->Release();
    m_context_menu = nullptr;
  }
  if (m_folder != nullptr) {
    m_folder->Release();
    m_folder = nullptr;
  }
  /* The child pidls point into these, so they are freed last. */
  for (PIDLIST_ABSOLUTE pidl : m_item_pidls) {
    ILFree(pidl);
  }
  m_item_pidls.clear();
  m_children.clear();
}

}  // namespace

/** \} */

/* -------------------------------------------------------------------- */
/** \name Public API
 * \{ */

bool GHOST_ShellMenuWin32_EnumerateLabels(const char *const *utf8_paths,
                                          int count,
                                          char ***r_labels,
                                          int *r_label_count)
{
  if (r_labels == nullptr || r_label_count == nullptr) {
    return false;
  }
  *r_labels = nullptr;
  *r_label_count = 0;

  ShellMenu shell_menu;
  if (!shell_menu.build(utf8_paths, count)) {
    return false;
  }

  const int item_count = GetMenuItemCount(shell_menu.menu());
  if (item_count <= 0) {
    return false;
  }

  char **labels = static_cast<char **>(malloc(sizeof(char *) * size_t(item_count)));
  if (labels == nullptr) {
    return false;
  }

  for (int i = 0; i < item_count; i++) {
    wchar_t text[256] = {0};
    GetMenuStringW(shell_menu.menu(), UINT(i), text, 256, MF_BYPOSITION);
    if (!utf16_to_utf8(text, &labels[i])) {
      GHOST_ShellMenuWin32_FreeLabels(labels, i);
      return false;
    }
  }

  *r_labels = labels;
  *r_label_count = item_count;
  return true;
}

void GHOST_ShellMenuWin32_FreeLabels(char **labels, int count)
{
  if (labels == nullptr) {
    return;
  }
  for (int i = 0; i < count; i++) {
    free(labels[i]);
  }
  free(labels);
}

bool GHOST_ShellMenuWin32_SupportsMenuMessages(const char *const *utf8_paths, int count)
{
  ShellMenu shell_menu;
  if (!shell_menu.build(utf8_paths, count)) {
    return false;
  }
  return shell_menu.has_menu_messages();
}

/* -------------------------------------------------------------------- */
/** \name Menu message forwarding
 *
 * `TrackPopupMenu` runs its own modal loop, so the messages a shell menu
 * extension needs never reach a window procedure of ours: `WM_INITMENUPOPUP` to
 * fill a submenu as it opens, `WM_DRAWITEM` and `WM_MEASUREITEM` to draw and
 * size its own items, and `WM_MENUCHAR` for keyboard accelerators. A
 * `WH_MSGFILTER` hook is the documented way to see them.
 *
 * The popup is synchronous and runs on the calling thread, so a single
 * file-scope pointer is enough - but it must be cleared before returning, or a
 * later menu would be handed another menu's messages.
 * \{ */

static ShellMenu *g_msgfilter_menu = nullptr;

static LRESULT CALLBACK shell_menu_msg_filter(int code, WPARAM wparam, LPARAM lparam)
{
  if (code == MSGF_MENU && g_msgfilter_menu != nullptr) {
    const MSG *msg = reinterpret_cast<const MSG *>(lparam);
    LRESULT result = 0;

    switch (msg->message) {
      case WM_INITMENUPOPUP:
      case WM_DRAWITEM:
      case WM_MEASUREITEM:
      case WM_MENUCHAR:
        if (g_msgfilter_menu->handle_menu_msg(msg->message, msg->wParam, msg->lParam, &result)) {
          return result;
        }
        break;
      default:
        break;
    }
  }

  return CallNextHookEx(nullptr, code, wparam, lparam);
}

/** \} */

bool GHOST_ShellMenuWin32_Popup(void *hwnd,
                                const char *const *utf8_paths,
                                int count,
                                int screen_x,
                                int screen_y)
{
  ShellMenu shell_menu;
  if (!shell_menu.build(utf8_paths, count)) {
    return false;
  }

  HWND window = static_cast<HWND>(hwnd);

  /* TrackPopupMenu only dismisses correctly if the owning window is in the
   * foreground, and the documented follow-up WM_NULL avoids the menu sticking
   * around afterwards. */
  SetForegroundWindow(window);

  /* Active only while the menu is up. */
  g_msgfilter_menu = &shell_menu;
  HHOOK hook = SetWindowsHookExW(
      WH_MSGFILTER, shell_menu_msg_filter, nullptr, GetCurrentThreadId());

  const int command = TrackPopupMenu(shell_menu.menu(),
                                     TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                     screen_x,
                                     screen_y,
                                     0,
                                     window,
                                     nullptr);

  if (hook != nullptr) {
    UnhookWindowsHookEx(hook);
  }
  g_msgfilter_menu = nullptr;

  PostMessage(window, WM_NULL, 0, 0);

  if (command == 0) {
    /* Dismissed without choosing anything. */
    return false;
  }

  const UINT offset = UINT(command) - kFirstId;

  CMINVOKECOMMANDINFOEX info;
  memset(&info, 0, sizeof(info));
  info.cbSize = sizeof(info);
  info.fMask = CMIC_MASK_UNICODE | CMIC_MASK_PTINVOKE;
  info.hwnd = window;
  info.lpVerb = MAKEINTRESOURCEA(offset);
  info.lpVerbW = MAKEINTRESOURCEW(offset);
  info.nShow = SW_SHOWNORMAL;
  info.ptInvoke.x = screen_x;
  info.ptInvoke.y = screen_y;

  return SUCCEEDED(
      shell_menu.context_menu()->InvokeCommand(reinterpret_cast<LPCMINVOKECOMMANDINFO>(&info)));
}

/** \} */

#endif /* _WIN32 */
