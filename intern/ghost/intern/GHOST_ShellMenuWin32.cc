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

 private:
  void destroy();

  IShellFolder *m_folder = nullptr;
  IContextMenu *m_context_menu = nullptr;
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

  /* CMF_EXTENDEDVERBS is what puts the entries Windows 11 keeps behind
   * "Show more options" into the menu. */
  const HRESULT result = m_context_menu->QueryContextMenu(
      m_menu, 0, kFirstId, kLastId, CMF_NORMAL | CMF_EXTENDEDVERBS);
  if (FAILED(result)) {
    return false;
  }

  return GetMenuItemCount(m_menu) > 0;
}

void ShellMenu::destroy()
{
  if (m_menu != nullptr) {
    DestroyMenu(m_menu);
    m_menu = nullptr;
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

  const int command = TrackPopupMenu(shell_menu.menu(),
                                     TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                     screen_x,
                                     screen_y,
                                     0,
                                     window,
                                     nullptr);

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
