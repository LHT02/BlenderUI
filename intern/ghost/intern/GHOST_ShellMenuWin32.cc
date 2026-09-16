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

#  include <cstdarg>
#  include <cstdio>
#  include <cstdlib>
#  include <cstring>
#  include <string>
#  include <vector>

#  include <windows.h>
#  include <shlobj.h>
#  include <shlwapi.h>
/* After `windows.h`, which they need - included before it they are a parse
 * error rather than a warning. `commoncontrols.h` is where `IImageList` and
 * `SHGetImageList` live, which is how an icon is fetched at a chosen size. */
#  include <commctrl.h>
#  include <commoncontrols.h>
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

/* Defined further down, next to the popup that uses it. Declared here so the
 * build path can be timed: every call in it runs third-party shell extension
 * code, and a slow extension is indistinguishable from a hang without timings.
 * A hang in here is exactly what "the menu entry does nothing" turned out to
 * be - the UI stops responding before the menu is ever created. */
static void shell_menu_log(const char *fmt, ...);

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

  /**
   * Take over a menu another thread built.
   *
   * `build()` is the half that runs third-party shell extension code and is
   * therefore the half that can hang, so it runs on a worker thread that can be
   * abandoned. `TrackPopupMenu` has to stay on the window's own thread, so the
   * result has to cross back: the interface is marshalled through a stream and
   * the menu handle is passed by value.
   */
  bool adopt(IStream *stream, HMENU menu);

  /** Hand the menu handle to the caller and forget it, so that this object's
   * destructor does not destroy a menu someone else now owns. */
  HMENU release_menu()
  {
    HMENU menu = m_menu;
    m_menu = nullptr;
    return menu;
  }

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
  const ULONGLONG t_start = GetTickCount64();
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
  shell_menu_log("  bind to parent: %llu ms", GetTickCount64() - t_start);

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
  /* This is where the shell loads the extensions registered for the file type,
   * so it is the expensive one. */
  shell_menu_log("  GetUIObjectOf: %llu ms", GetTickCount64() - t_start);

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
  shell_menu_log("  QueryContextMenu: %llu ms (hr=0x%08lX, items=%d)",
                 GetTickCount64() - t_start,
                 (unsigned long)result,
                 (int)GetMenuItemCount(m_menu));
  if (FAILED(result)) {
    return false;
  }

  return GetMenuItemCount(m_menu) > 0;
}

bool ShellMenu::adopt(IStream *stream, HMENU menu)
{
  if (stream == nullptr || menu == nullptr) {
    return false;
  }

  void *iface = nullptr;
  if (FAILED(CoGetInterfaceAndReleaseStream(stream, IID_IContextMenu, &iface)) || iface == nullptr) {
    return false;
  }
  m_context_menu = static_cast<IContextMenu *>(iface);
  m_menu = menu;

  /* The same question `build()` asks, asked again in this apartment: the
   * interface that came across is a proxy, so the shell's own object has to be
   * queried for its message-aware flavour here rather than there. */
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
    m_context_menu2 = m_context_menu3;
  }

  return true;
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

/** \} */

/* -------------------------------------------------------------------- */
/** \name Diagnostics
 *
 * BLUI has no info bar, so a shell menu that fails leaves nothing behind at
 * all - which is how it was reported ("the entry does nothing"). The popup
 * path cannot show a dialog for every outcome either, because dismissing the
 * menu on purpose is not a failure. So it appends to a log file instead, and
 * `%TEMP%\blui_shellmenu.log` is the first thing to read when the menu does not
 * appear.
 * \{ */

static void shell_menu_log(const char *fmt, ...)
{
  char path[MAX_PATH];
  const DWORD len = GetTempPathA(MAX_PATH, path);
  if (len == 0 || len + 32 >= MAX_PATH) {
    return;
  }
  strcat_s(path, MAX_PATH, "blui_shellmenu.log");

  FILE *file = nullptr;
  if (fopen_s(&file, path, "a") != 0 || file == nullptr) {
    return;
  }
  va_list args;
  va_start(args, fmt);
  vfprintf(file, fmt, args);
  va_end(args);
  fputc('\n', file);
  fclose(file);
}

/** \} */

/**
 * How long `build()` gets before it is abandoned.
 *
 * This is the only defence against an installed shell extension that hangs
 * inside `QueryContextMenu`, which is exactly what happens on the machine this
 * was written on: BLUI called it on the main thread and the whole UI stopped
 * responding, which is how "the shell menu entry does nothing" was reported.
 *
 * The thread cannot be killed - it is inside third-party code holding unknown
 * locks - so a timeout leaves it running and never answers. Five seconds is
 * generous for loading extensions (measured at 16 ms for `GetUIObjectOf`) while
 * still being short enough that a person does not conclude the app has died.
 */
constexpr DWORD kBuildTimeoutMs = 5000;

/** What the worker thread produces, and how it says it is finished. */
struct ShellMenuBuildJob {
  std::vector<std::string> paths;
  HANDLE done = nullptr;
  bool ok = false;
  IStream *stream = nullptr;
  HMENU menu = nullptr;
};

static DWORD WINAPI shell_menu_build_thread(void *param)
{
  ShellMenuBuildJob *job = static_cast<ShellMenuBuildJob *>(param);
  const HRESULT ole = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

  {
    std::vector<const char *> raw;
    raw.reserve(job->paths.size());
    for (const std::string &path : job->paths) {
      raw.push_back(path.c_str());
    }

    ShellMenu menu;
    if (menu.build(raw.data(), int(raw.size()))) {
      IStream *stream = nullptr;
      if (SUCCEEDED(CoMarshalInterThreadInterfaceInStream(
              IID_IContextMenu, menu.context_menu(), &stream)))
      {
        job->stream = stream;
        job->menu = menu.release_menu();
        job->ok = true;
      }
    }
    /* `menu` is destroyed here, on the thread that created its COM objects -
     * releasing them from the other apartment would be wrong. The menu handle
     * has already been detached above. */
  }

  if (SUCCEEDED(ole)) {
    CoUninitialize();
  }
  SetEvent(job->done);
  return 0;
}

bool GHOST_ShellMenuWin32_Popup(void *hwnd,
                                const char *const *utf8_paths,
                                int count,
                                int screen_x,
                                int screen_y)
{
  if (utf8_paths == nullptr || count <= 0) {
    return false;
  }

  /* The paths belong to the caller and are freed as soon as this returns, so
   * the worker needs its own copy. */
  ShellMenuBuildJob *job = new ShellMenuBuildJob();
  job->paths.assign(utf8_paths, utf8_paths + count);
  job->done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  if (job->done == nullptr) {
    delete job;
    return false;
  }

  const ULONGLONG t_start = GetTickCount64();
  HANDLE thread = CreateThread(nullptr, 0, shell_menu_build_thread, job, 0, nullptr);
  if (thread == nullptr) {
    CloseHandle(job->done);
    delete job;
    return false;
  }

  if (WaitForSingleObject(job->done, kBuildTimeoutMs) != WAIT_OBJECT_0) {
    shell_menu_log("build abandoned after %lu ms - a shell extension is hung in "
                   "QueryContextMenu. The worker thread is left running; it cannot be "
                   "killed safely.",
                   (unsigned long)kBuildTimeoutMs);
    /* `job`, its event and the thread handle are deliberately leaked. The thread
     * is alive inside third-party code and will call SetEvent() if it ever
     * wakes, so closing the handles now would be a use-after-free, and freeing
     * `job` would hand it a dangling pointer. One leaked thread per hung attempt
     * is the price of not killing the application instead. */
    CloseHandle(thread);
    MessageBoxW(static_cast<HWND>(hwnd),
                L"The Windows shell menu did not respond in time and was cancelled.\n\n"
                L"An installed shell extension is hung while building the menu for this "
                L"file. BLUI is still usable; the extension should be updated or removed.",
                L"BLUI - Shell Menu",
                MB_OK | MB_ICONWARNING);
    return false;
  }

  const ULONGLONG elapsed = GetTickCount64() - t_start;
  CloseHandle(thread);
  CloseHandle(job->done);
  job->done = nullptr;

  if (!job->ok) {
    shell_menu_log("build FAILED for %d path(s), first=%s (after %llu ms)",
                   count,
                   utf8_paths[0],
                   elapsed);
    delete job;
    /* BLUI has no info bar, so a failed build is indistinguishable from a menu
     * entry that does nothing. Say so out loud instead. */
    MessageBoxW(static_cast<HWND>(hwnd),
                L"The Windows shell menu could not be built for the selected file(s).\n\n"
                L"This normally means the shell extension that owns the file type did not "
                L"respond to the shell's IContextMenu request.",
                L"BLUI - Shell Menu",
                MB_OK | MB_ICONWARNING);
    return false;
  }

  shell_menu_log("build ok for %d path(s), first=%s (%llu ms, %d item(s))",
                 count,
                 utf8_paths[0],
                 elapsed,
                 (int)GetMenuItemCount(job->menu));

  ShellMenu shell_menu;
  if (!shell_menu.adopt(job->stream, job->menu)) {
    shell_menu_log("the built menu could not be taken over in this apartment");
    DestroyMenu(job->menu);
    delete job;
    return false;
  }
  /* `adopt` consumed the stream; `job` holds nothing else that needs freeing. */
  delete job;

  HWND window = static_cast<HWND>(hwnd);

  /* TrackPopupMenu only dismisses correctly if the owning window is in the
   * foreground, and the documented follow-up WM_NULL avoids the menu sticking
   * around afterwards. A refused SetForegroundWindow is the classic reason the
   * menu never appears, so its result is recorded rather than assumed. */
  const BOOL was_foreground = SetForegroundWindow(window);
  shell_menu_log("SetForegroundWindow -> %d (already foreground=%d)",
                 (int)was_foreground,
                 (int)(GetForegroundWindow() == window));

  /* Active only while the menu is up. */
  g_msgfilter_menu = &shell_menu;
  HHOOK hook = SetWindowsHookExW(
      WH_MSGFILTER, shell_menu_msg_filter, nullptr, GetCurrentThreadId());
  shell_menu_log("msg filter hook=%p", (void *)hook);

  const int command = TrackPopupMenu(shell_menu.menu(),
                                     TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_LEFTALIGN |
                                         TPM_TOPALIGN,
                                     screen_x,
                                     screen_y,
                                     0,
                                     window,
                                     nullptr);

  shell_menu_log("TrackPopupMenu at (%d,%d) -> command=%d (err=%lu)",
                 screen_x,
                 screen_y,
                 command,
                 (unsigned long)GetLastError());

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

  if (SUCCEEDED(shell_menu.context_menu()->InvokeCommand(
          reinterpret_cast<LPCMINVOKECOMMANDINFO>(&info))))
  {
    shell_menu_log("InvokeCommand by offset %u ok", offset);
    return true;
  }
  shell_menu_log("InvokeCommand by offset %u failed, trying canonical verb", offset);

  /* Some extensions answer only to their canonical verb, not to the menu
   * offset they were handed - they populate the menu and then fail to
   * recognise their own command id. Ask for the verb and try once more, rather
   * than reporting a failure the user can do nothing about.
   *
   * `GCS_VERBW` writes a wide string, and the API takes it as `char *` because
   * the A and W variants share a signature. */
  wchar_t verb[128] = {0};
  if (FAILED(shell_menu.context_menu()->GetCommandString(
          offset, GCS_VERBW, nullptr, reinterpret_cast<char *>(verb), 128)))
  {
    return false;
  }
  if (verb[0] == L'\0') {
    return false;
  }

  memset(&info, 0, sizeof(info));
  info.cbSize = sizeof(info);
  info.fMask = CMIC_MASK_UNICODE | CMIC_MASK_PTINVOKE;
  info.hwnd = window;
  info.lpVerbW = verb;
  info.nShow = SW_SHOWNORMAL;
  info.ptInvoke.x = screen_x;
  info.ptInvoke.y = screen_y;

  return SUCCEEDED(
      shell_menu.context_menu()->InvokeCommand(reinterpret_cast<LPCMINVOKECOMMANDINFO>(&info)));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name File icons
 * \{ */

bool GHOST_ShellMenuWin32_LoadFileIconRgba(const char *utf8_path,
                                           unsigned char **r_pixels,
                                           int *r_width,
                                           int *r_height)
{
  if (utf8_path == nullptr || r_pixels == nullptr || r_width == nullptr || r_height == nullptr) {
    return false;
  }
  *r_pixels = nullptr;
  *r_width = 0;
  *r_height = 0;

  std::wstring wide;
  if (!utf8_to_utf16(utf8_path, wide)) {
    return false;
  }

  /* The *index* into the system image list, rather than a ready `HICON`:
   * `SHGFI_ICON` only ever returns the small system icon, while going through
   * the image list lets the size be chosen. */
  SHFILEINFOW file_info = {};
  DWORD_PTR got = SHGetFileInfoW(
      wide.c_str(), 0, &file_info, sizeof(file_info), SHGFI_SYSICONINDEX);
  if (got == 0) {
    /* A path that does not resolve yet still has an icon, if the shell is told
     * what kind of thing it is. */
    const DWORD attributes = PathIsDirectoryW(wide.c_str()) ? FILE_ATTRIBUTE_DIRECTORY :
                                                              FILE_ATTRIBUTE_NORMAL;
    got = SHGetFileInfoW(wide.c_str(),
                         attributes,
                         &file_info,
                         sizeof(file_info),
                         SHGFI_SYSICONINDEX | SHGFI_USEFILEATTRIBUTES);
  }
  if (got == 0) {
    return false;
  }

  /* Largest first: the caller scales down, and a shortcut's icon is only
   * recognisable at a decent size. */
  const int tiers[] = {SHIL_JUMBO, SHIL_EXTRALARGE, SHIL_LARGE, SHIL_SMALL};
  HICON icon = nullptr;
  for (int tier : tiers) {
    IImageList *image_list = nullptr;
    if (FAILED(SHGetImageList(tier, IID_IImageList, reinterpret_cast<void **>(&image_list))) ||
        image_list == nullptr)
    {
      continue;
    }
    image_list->GetIcon(file_info.iIcon, ILD_TRANSPARENT, &icon);
    image_list->Release();
    if (icon != nullptr) {
      break;
    }
  }
  if (icon == nullptr) {
    return false;
  }

  /* The real size, rather than an assumption about it - the image list tier
   * that answered decides this. */
  int width = GetSystemMetrics(SM_CXICON);
  int height = GetSystemMetrics(SM_CYICON);
  ICONINFO icon_info = {};
  if (GetIconInfo(icon, &icon_info)) {
    BITMAP bitmap = {};
    if (icon_info.hbmColor != nullptr && GetObjectW(icon_info.hbmColor, sizeof(bitmap), &bitmap)) {
      width = bitmap.bmWidth;
      height = bitmap.bmHeight;
    }
    if (icon_info.hbmColor != nullptr) {
      DeleteObject(icon_info.hbmColor);
    }
    if (icon_info.hbmMask != nullptr) {
      DeleteObject(icon_info.hbmMask);
    }
  }
  if (width <= 0 || height <= 0) {
    DestroyIcon(icon);
    return false;
  }

  BITMAPV5HEADER header = {};
  header.bV5Size = sizeof(header);
  header.bV5Width = width;
  header.bV5Height = -height; /* Top-down, so row 0 is the top of the icon. */
  header.bV5Planes = 1;
  header.bV5BitCount = 32;
  header.bV5Compression = BI_BITFIELDS;
  header.bV5RedMask = 0x00FF0000;
  header.bV5GreenMask = 0x0000FF00;
  header.bV5BlueMask = 0x000000FF;
  header.bV5AlphaMask = 0xFF000000;

  HDC screen_dc = GetDC(nullptr);
  if (screen_dc == nullptr) {
    DestroyIcon(icon);
    return false;
  }

  void *bits = nullptr;
  HBITMAP dib = CreateDIBSection(
      screen_dc, reinterpret_cast<BITMAPINFO *>(&header), DIB_RGB_COLORS, &bits, nullptr, 0);
  HDC memory_dc = CreateCompatibleDC(screen_dc);
  ReleaseDC(nullptr, screen_dc);

  if (dib == nullptr || memory_dc == nullptr || bits == nullptr) {
    if (memory_dc != nullptr) {
      DeleteDC(memory_dc);
    }
    if (dib != nullptr) {
      DeleteObject(dib);
    }
    DestroyIcon(icon);
    return false;
  }

  HGDIOBJ old_bitmap = SelectObject(memory_dc, dib);
  /* Cleared first: a transparent icon leaves its pixels untouched, so an
   * uninitialised DIB would be handed back as garbage. */
  memset(bits, 0, size_t(width) * size_t(height) * 4);
  DrawIconEx(memory_dc, 0, 0, icon, width, height, 0, nullptr, DI_NORMAL);
  SelectObject(memory_dc, old_bitmap);

  DeleteDC(memory_dc);
  DestroyIcon(icon);

  unsigned char *pixels = static_cast<unsigned char *>(
      malloc(size_t(width) * size_t(height) * 4));
  if (pixels == nullptr) {
    DeleteObject(dib);
    return false;
  }

  const unsigned char *src = static_cast<const unsigned char *>(bits);
  for (int i = 0, count = width * height; i < count; i++) {
    /* The DIB is BGRA; the caller wants RGBA. */
    pixels[i * 4 + 0] = src[i * 4 + 2];
    pixels[i * 4 + 1] = src[i * 4 + 1];
    pixels[i * 4 + 2] = src[i * 4 + 0];
    pixels[i * 4 + 3] = src[i * 4 + 3];
  }

  DeleteObject(dib);

  *r_pixels = pixels;
  *r_width = width;
  *r_height = height;
  return true;
}

void GHOST_ShellMenuWin32_FreeIconRgba(unsigned char *pixels)
{
  free(pixels);
}

/** \} */

#endif /* _WIN32 */
