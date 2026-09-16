/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/**
 * Self test for BLUI's Windows shell context menu.
 *
 * The interactive part (TrackPopupMenu) needs a user, but everything that is
 * easy to get wrong does not: parsing the paths, finding the common parent
 * folder, binding to it, getting an IContextMenu off it, letting the shell
 * populate the menu, and reading the resulting item labels back. That is what
 * this checks.
 *
 * Build (from the repository root, with the MSVC environment loaded):
 *   cl /nologo /EHsc /std:c++17 /utf-8 ^
 *      /I intern\ghost /I intern\ghost\intern ^
 *      blui\tools\shellmenu_selftest.cc intern\ghost\intern\GHOST_ShellMenuWin32.cc ^
 *      /Fe:build\shellmenu_selftest.exe /link ole32.lib shell32.lib shlwapi.lib user32.lib
 */

#include <cstdio>
#include <cstring>

#include <windows.h>
#include <ole2.h>
#include <shlobj.h>

#include "GHOST_ShellMenuWin32.hh"

static int g_failures = 0;

static void check(bool condition, const char *what)
{
  printf("%s %s\n", condition ? "  ok  " : " FAIL ", what);
  if (!condition) {
    g_failures++;
  }
}

/* A build output that always exists once the project has been built, plus its
 * folder, so the test does not depend on the user's own files. */
static const char *g_exe = "D:\\BlenderUI\\build\\bin\\BLUI.exe";
static const char *g_dir = "D:\\BlenderUI\\build\\bin";

static void test_menu_for_file()
{
  printf("menu for a file:\n");

  const char *paths[1] = {g_exe};
  char **labels = nullptr;
  int label_count = 0;

  const bool ok = GHOST_ShellMenuWin32_EnumerateLabels(paths, 1, &labels, &label_count);
  check(ok, "EnumerateLabels succeeds for an existing file");
  if (!ok) {
    return;
  }

  check(label_count > 0, "the shell populated the menu");

  /* The shell always offers "Open" (possibly localised) and "Properties" for a
   * file. Rather than depend on the display language, check that at least one
   * non-empty label came back and print them all for inspection. */
  int non_empty = 0;
  for (int i = 0; i < label_count; i++) {
    if (labels[i] != nullptr && labels[i][0] != '\0') {
      non_empty++;
    }
  }
  check(non_empty > 0, "the menu has at least one named entry");

  printf("      %d items:\n", label_count);
  for (int i = 0; i < label_count; i++) {
    printf("        [%2d] %s\n", i, (labels[i] != nullptr && labels[i][0] != '\0')
                                       ? labels[i]
                                       : "(separator)");
  }

  GHOST_ShellMenuWin32_FreeLabels(labels, label_count);
}

static void test_menu_for_directory()
{
  printf("menu for a directory:\n");

  const char *paths[1] = {g_dir};
  char **labels = nullptr;
  int label_count = 0;

  const bool ok = GHOST_ShellMenuWin32_EnumerateLabels(paths, 1, &labels, &label_count);
  check(ok, "EnumerateLabels succeeds for an existing directory");
  if (ok) {
    check(label_count > 0, "the directory menu is not empty");
    GHOST_ShellMenuWin32_FreeLabels(labels, label_count);
  }
}

static void test_multi_selection()
{
  printf("menu for a multi selection:\n");

  const char *paths[2] = {
      "D:\\BlenderUI\\build\\bin\\BLUI.exe",
      "D:\\BlenderUI\\build\\bin\\BLUI-launcher.exe",
  };
  char **labels = nullptr;
  int label_count = 0;

  const bool ok = GHOST_ShellMenuWin32_EnumerateLabels(paths, 2, &labels, &label_count);
  check(ok, "EnumerateLabels succeeds for two files in one folder");
  if (ok) {
    check(label_count > 0, "the multi selection menu is not empty");
    GHOST_ShellMenuWin32_FreeLabels(labels, label_count);
  }
}

/**
 * Whether the shell's menu object wants its messages forwarded.
 *
 * This is the half of the popup path that no other check here can see.
 * `QueryContextMenu` produces the top-level entries whether or not anything
 * forwards `WM_INITMENUPOPUP` to `HandleMenuMsg2()`, so a menu that enumerates
 * perfectly can still come up with every extension submenu empty - which is
 * what 7-Zip's and TortoiseSVN's did. Behaving correctly needs a menu that
 * implements `IContextMenu2` or `IContextMenu3`, and this asserts one is there.
 */
static void test_menu_messages()
{
  printf("menu message forwarding:\n");

  const char *paths[1] = {g_exe};
  check(GHOST_ShellMenuWin32_SupportsMenuMessages(paths, 1),
        "the shell's menu object implements IContextMenu2 or IContextMenu3");
}

static void test_missing_path()
{
  printf("bad input:\n");


  const char *paths[1] = {"D:\\BlenderUI\\this\\does\\not\\exist.txt"};
  char **labels = nullptr;
  int label_count = 0;
  check(!GHOST_ShellMenuWin32_EnumerateLabels(paths, 1, &labels, &label_count),
        "a missing path is rejected rather than crashing");
  check(labels == nullptr && label_count == 0, "nothing is handed back on failure");

  check(!GHOST_ShellMenuWin32_EnumerateLabels(nullptr, 0, &labels, &label_count),
        "a null path list is rejected");
}

int main()
{
  const HRESULT ole = OleInitialize(nullptr);
  printf("OleInitialize -> 0x%08lX\n", (unsigned long)ole);

  /* Does the file we test with actually exist? If not, say so instead of
   * reporting a confusing cascade of failures. */
  const DWORD attributes = GetFileAttributesA(g_exe);
  printf("test file: %s (%s)\n",
         g_exe,
         (attributes == INVALID_FILE_ATTRIBUTES) ? "MISSING - build first" : "present");

  test_menu_for_file();
  test_menu_for_directory();
  test_multi_selection();
  test_menu_messages();
  test_missing_path();

  printf("\n%s (%d failure%s)\n",
         g_failures == 0 ? "PASS" : "FAIL",
         g_failures,
         g_failures == 1 ? "" : "s");

  if (SUCCEEDED(ole)) {
    OleUninitialize();
  }
  return g_failures == 0 ? 0 : 1;
}
