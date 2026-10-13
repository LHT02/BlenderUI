/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#include <array>
#include <cstdio>
#include <cwchar>
#include <string>
#include <windows.h>

/** A DESKTOP-only creation scope. Never changes process DPI or an existing HWND. */
class GHOST_BluiDesktopDpiScope {
  struct WindowIdentity {
    HWND handle = nullptr;
    DWORD thread = 0;
    const wchar_t *name = nullptr;
  };

  bool m_enabled;
  bool m_ready = false;
  HANDLE m_process = nullptr;
  DWORD m_pid = 0;
  FILETIME m_started = {};
  WindowIdentity m_root, m_host, m_view, m_list;
  unsigned m_visited = 0, m_candidates = 0;
  /* GHOST still targets Win8 headers. Resolve modern APIs from already-loaded
   * system User32 without changing the global target or loading Shell DLLs. */
  using WindowContextFn = HANDLE(WINAPI *)(HWND);
  using ThreadContextFn = HANDLE(WINAPI *)();
  using SetContextFn = HANDLE(WINAPI *)(HANDLE);
  using EqualContextFn = BOOL(WINAPI *)(HANDLE, HANDLE);
  WindowContextFn m_window_context = nullptr;
  ThreadContextFn m_thread_context = nullptr;
  SetContextFn m_set_context = nullptr;
  EqualContextFn m_equal_context = nullptr;
  HANDLE m_context = nullptr, m_previous = nullptr;
  const char *m_error = "Windows Explorer desktop could not be verified";

  bool identify(HWND handle, const wchar_t *name, WindowIdentity &result) const
  {
    DWORD pid = 0;
    const DWORD thread = GetWindowThreadProcessId(handle, &pid);
    wchar_t actual[256] = {};
    if (!handle || !thread || pid != m_pid ||
        !GetClassNameW(handle, actual, 256) || wcscmp(actual, name)) {
      return false;
    }
    result = {handle, thread, name};
    return true;
  }

  bool matches(const WindowIdentity &saved) const
  {
    WindowIdentity current;
    return identify(saved.handle, saved.name, current) && current.thread == saved.thread;
  }

  bool child(const WindowIdentity &parent, const wchar_t *name, WindowIdentity &result) const
  {
    const HWND handle = FindWindowExW(parent.handle, nullptr, name, nullptr);
    return handle && !FindWindowExW(parent.handle, handle, name, nullptr) &&
           GetParent(handle) == parent.handle && identify(handle, name, result);
  }

  void candidate(const WindowIdentity &host)
  {
    WindowIdentity view;
    if (child(host, L"SHELLDLL_DefView", view)) {
      m_candidates++;
      m_host = host;
      m_view = view;
    }
  }

  static BOOL CALLBACK visit(HWND handle, LPARAM value)
  {
    auto *scope = reinterpret_cast<GHOST_BluiDesktopDpiScope *>(value);
    if (++scope->m_visited > 4096) {
      return FALSE;
    }
    WindowIdentity worker;
    if (!GetParent(handle) && scope->identify(handle, L"WorkerW", worker)) {
      scope->candidate(worker);
    }
    return TRUE;
  }

  bool fresh_chain() const
  {
    FILETIME started, exited, kernel, user;
    WindowIdentity view, list;
    return m_process && WaitForSingleObject(m_process, 0) == WAIT_TIMEOUT &&
           GetProcessTimes(m_process, &started, &exited, &kernel, &user) &&
           started.dwLowDateTime == m_started.dwLowDateTime &&
           started.dwHighDateTime == m_started.dwHighDateTime &&
           GetShellWindow() == m_root.handle && matches(m_root) && matches(m_host) &&
           matches(m_view) && matches(m_list) &&
           (m_host.handle == m_root.handle || !GetParent(m_host.handle)) &&
           child(m_host, L"SHELLDLL_DefView", view) && view.handle == m_view.handle &&
           child(m_view, L"SysListView32", list) && list.handle == m_list.handle;
  }

  bool discover()
  {
    const HWND root = GetShellWindow();
    if (!root || !GetWindowThreadProcessId(root, &m_pid) || !m_pid ||
        !identify(root, L"Progman", m_root)) {
      return false;
    }
    m_process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, m_pid);
    if (!m_process) {
      return false;
    }
    FILETIME exited, kernel, user;
    std::array<wchar_t, 32768> executable = {}, windows = {};
    DWORD length = DWORD(executable.size());
    const UINT directory_length = GetWindowsDirectoryW(windows.data(), UINT(windows.size()));
    if (!directory_length || directory_length >= windows.size() ||
        !QueryFullProcessImageNameW(m_process, 0, executable.data(), &length) ||
        !GetProcessTimes(m_process, &m_started, &exited, &kernel, &user)) {
      return false;
    }
    std::wstring expected(windows.data(), directory_length);
    expected += L"\\explorer.exe";
    if (_wcsicmp(executable.data(), expected.c_str()) != 0) {
      return false;
    }
    candidate(m_root);
    if (!EnumWindows(visit, reinterpret_cast<LPARAM>(this)) || m_candidates != 1 ||
        !child(m_view, L"SysListView32", m_list) || !fresh_chain()) {
      return false;
    }
    m_context = m_window_context(m_host.handle);
    return m_context != nullptr;
  }

 public:
  explicit GHOST_BluiDesktopDpiScope(bool enabled) : m_enabled(enabled)
  {
    if (!enabled) {
      m_ready = true;
      return;
    }
    HMODULE user = GetModuleHandleW(L"user32.dll");
    if (user) {
      m_window_context = reinterpret_cast<WindowContextFn>(GetProcAddress(user, "GetWindowDpiAwarenessContext"));
      m_thread_context = reinterpret_cast<ThreadContextFn>(GetProcAddress(user, "GetThreadDpiAwarenessContext"));
      m_set_context = reinterpret_cast<SetContextFn>(GetProcAddress(user, "SetThreadDpiAwarenessContext"));
      m_equal_context = reinterpret_cast<EqualContextFn>(GetProcAddress(user, "AreDpiAwarenessContextsEqual"));
    }
    if (!m_window_context || !m_thread_context || !m_set_context || !m_equal_context) {
      m_error = "Desktop DPI APIs unavailable";
      return;
    }
    if (!discover()) {
      return;
    }
    m_error = "Could not match verified desktop host creation DPI";
    m_previous = m_set_context(m_context);
    m_ready = m_previous && fresh_chain() &&
              m_equal_context(m_thread_context(), m_context);
  }

  ~GHOST_BluiDesktopDpiScope()
  {
    if (m_previous && !m_set_context(m_previous)) {
      fprintf(stderr, "BLUI: failed to restore desktop creation thread DPI (%lu)\n", GetLastError());
    }
    if (m_process) {
      CloseHandle(m_process);
    }
  }

  GHOST_BluiDesktopDpiScope(const GHOST_BluiDesktopDpiScope &) = delete;
  GHOST_BluiDesktopDpiScope &operator=(const GHOST_BluiDesktopDpiScope &) = delete;

  bool ready() const { return m_ready; }
  const char *error() const { return m_error; }

  bool window_matches(HWND window) const
  {
    return !m_enabled ||
           (window && fresh_chain() &&
            m_equal_context(m_window_context(m_host.handle), m_context) &&
            m_equal_context(m_window_context(window), m_context));
  }
};
