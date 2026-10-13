/* SPDX-License-Identifier: GPL-2.0-or-later */
/** Disposable icon extraction host. Shell extensions never enter BLUI's UI process. */
#include <cstdio>
#include <cstdint>
#include <string>
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#include "GHOST_ShellMenuWin32.hh"

static DWORD WINAPI icon_watchdog(void *)
{
  /* The Python parent can be cancelled while a Shell provider is blocked.
   * This independent deadline kills only this disposable extraction host. */
  Sleep(2500);
  TerminateProcess(GetCurrentProcess(), 124);
  return 0;
}

int wmain(int argc, wchar_t **argv)
{
  if (argc != 2) {
    return 2;
  }
  HANDLE watchdog = CreateThread(nullptr, 0, icon_watchdog, nullptr, 0, nullptr);
  if (!watchdog) {
    return 125;
  }
  CloseHandle(watchdog);
  SetPriorityClass(GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS);
  const int length = WideCharToMultiByte(CP_UTF8, 0, argv[1], -1, nullptr, 0, nullptr, nullptr);
  if (length <= 1 || length > 131072) {
    return 2;
  }
  std::string path(length, '\0');
  WideCharToMultiByte(CP_UTF8, 0, argv[1], -1, path.data(), length, nullptr, nullptr);
  unsigned char *pixels = nullptr;
  int width = 0, height = 0;
  if (!GHOST_ShellMenuWin32_LoadFileIconRgba(path.c_str(), &pixels, &width, &height)) {
    return 3;
  }
  int result = 4;
  if (pixels && width > 0 && height > 0 && width <= 1024 && height <= 1024) {
    _setmode(_fileno(stdout), _O_BINARY);
    const uint32_t header[] = {uint32_t(width), uint32_t(height)};
    const size_t bytes = size_t(width) * height * 4;
    if (fwrite(header, sizeof(header), 1, stdout) == 1 &&
        fwrite(pixels, 1, bytes, stdout) == bytes && fflush(stdout) == 0) {
      result = 0;
    }
  }
  GHOST_ShellMenuWin32_FreeIconRgba(pixels);
  return result;
}
