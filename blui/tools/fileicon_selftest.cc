/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2026 BLUI */
/** No-window regression for the real GHOST shortcut-icon loader.
 * Build with GHOST_FileIconWin32.cc + GHOST_IconResourceWin32.cc, linking
 * ole32 uuid shell32 shlwapi user32 gdi32 comctl32. Then pass the exe to
 * check_shortcut_icon_quality.py, which owns all icon/link fixtures. */
#include <cstdio>
#include <cstdlib>
#include <string>

#include <windows.h>

#include "GHOST_ShellMenuWin32.hh"

static int failures = 0;

static void check(const bool condition, const char *description)
{
  printf("%s %s\n", condition ? "PASS" : "FAIL", description);
  failures += !condition;
}

static std::string utf8(const wchar_t *value)
{
  const int size = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
  std::string result(size, '\0');
  WideCharToMultiByte(CP_UTF8, 0, value, -1, result.data(), size, nullptr, nullptr);
  return result;
}

static void test_icon(const std::wstring &root, const wchar_t *name, const int expected_size)
{
  printf("Icon: %ls\n", name);
  const std::string path = utf8((root + L"\\" + name).c_str());
  unsigned char *pixels = nullptr;
  int width = 0, height = 0;
  const bool loaded = GHOST_ShellMenuWin32_LoadFileIconRgba(
      path.c_str(), &pixels, &width, &height);
  check(loaded && pixels, "icon loaded");
  if (!loaded || !pixels) {
    return;
  }
  printf("Original resolution: %d x %d\n", width, height);
  check(width == expected_size && height == expected_size, "largest intrinsic resource selected");
  if (width == expected_size && height == expected_size) {
    const auto pixel = [&](int x, int y) { return pixels + (y * width + x) * 4; };
    if (expected_size >= 64) {
      const auto *top = pixel(width / 2, 2);
      const auto *bottom = pixel(width / 2, height - 3);
      check(top[2] > 250 && top[0] < 5 && bottom[0] > 250 && bottom[2] < 5,
            "top-down orientation preserved");
      const auto *green = pixel(16, 20);
      const auto *white = pixel(17, 20);
      check(green[0] < 5 && green[1] > 250 && white[0] > 250 && white[1] > 250,
            "one-pixel detail preserved without a resampled Shell tier");
      const auto *alpha = pixel(width / 2, height - 10);
      check(std::abs(int(alpha[0]) - 64) <= 2 && std::abs(int(alpha[1]) - 128) <= 2 &&
                std::abs(int(alpha[2]) - 192) <= 2 && std::abs(int(alpha[3]) - 128) <= 1,
            "straight alpha preserved without double-darkening edges");
    }
    else {
      const auto *center = pixel(width / 2, height / 2);
      check(center[0] < 5 && center[1] > 250 && center[2] < 5,
            "small or fallback resource remains valid");
      if (expected_size == 20) {
        check(pixel(0, 0)[3] == 0 && pixel(2, 2)[1] > 250,
              "16px artwork cropped from a padded 256px canvas with transparent margin");
      }
    }
  }
  GHOST_ShellMenuWin32_FreeIconRgba(pixels);
}

int wmain(int argc, wchar_t **argv)
{
  if (argc != 2) {
    fprintf(stderr, "Usage: fileicon_selftest.exe <fixture-directory>\n");
    return 2;
  }
  const std::wstring root = argv[1];
  test_icon(root, L"PNG.lnk", 256);
  test_icon(root, L"BMP.lnk", 64);
  test_icon(root, L"Environment.lnk", 256);
  test_icon(root, L"Small.lnk", 16);
  test_icon(root, L"Padded.lnk", 20);
  test_icon(root, L"Damaged.lnk", 32);
  if (GetFileAttributesW((root + L"\\PE.lnk").c_str()) != INVALID_FILE_ATTRIBUTES) {
    test_icon(root, L"PE.lnk", 256);
    test_icon(root, L"PEIndex.lnk", 64);
    test_icon(root, L"PETarget.lnk", 256);
    check(GetFileAttributesW((root + L"\\executed.txt").c_str()) == INVALID_FILE_ATTRIBUTES,
          "icon DLL DllMain was never executed");
  }
  printf("fileicon_selftest: %s (%d failures)\n", failures ? "FAIL" : "PASS", failures);
  return failures ? 1 : 0;
}
