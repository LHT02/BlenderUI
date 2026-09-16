/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/**
 * Self test for BLUI's Windows OLE drop source.
 *
 * Building a drag payload and interrogating the COM object does not need a
 * window or a real drag, so this can run head-less. It checks the two things
 * that are easy to get subtly wrong and impossible to notice by eye:
 *
 *  - the `CF_HDROP` layout (DROPFILES header, wide characters, double NUL
 *    termination, non-ASCII paths surviving the round trip)
 *  - the COM contract Explorer actually exercises (QueryGetData, GetData,
 *    EnumFormatEtc)
 *
 * Build (from the repository root, with the MSVC environment loaded):
 *   cl /nologo /EHsc /std:c++17 /utf-8 ^
 *      /I intern\ghost /I intern\ghost\intern ^
 *      blui\tools\dragsource_selftest.cc intern\ghost\intern\GHOST_DragSourceWin32.cc ^
 *      /Fe:build\dragsource_selftest.exe /link ole32.lib shell32.lib user32.lib
 */

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include <windows.h>
#include <ole2.h>
#include <shlobj.h>

#include "GHOST_DragSourceWin32.hh"

static int g_failures = 0;

static void check(bool condition, const char *what)
{
  printf("%s %s\n", condition ? "  ok  " : " FAIL ", what);
  if (!condition) {
    g_failures++;
  }
}

static const char *const g_paths[] = {
    "C:\\Users\\Public\\Pictures\\sample.png",
    "D:\\BlenderUI\\build\\bin\\BLUI.exe",
    "C:\\Users\\LHT02\\Pictures\\\xE6\xB5\x8B\xE8\xAF\x95\xE5\x9B\xBE\xE7\x89\x87.png",
    "C:\\Program Files\\Some App\\file with spaces.txt",
};

static const int g_path_count = int(sizeof(g_paths) / sizeof(g_paths[0]));

static void test_payload()
{
  printf("payload:\n");
  HGLOBAL hdrop = GHOST_DragSourceWin32_CreateHDrop(g_paths, g_path_count);
  check(hdrop != nullptr, "CreateHDrop returns a handle");
  if (hdrop == nullptr) {
    return;
  }

  /* Validate the structure through the raw pointer, not just by reading back. */
  const BYTE *base = static_cast<const BYTE *>(GlobalLock(hdrop));
  const DROPFILES *df = reinterpret_cast<const DROPFILES *>(base);
  check(df->pFiles == sizeof(DROPFILES), "DROPFILES::pFiles points past the header");
  check(df->fWide == TRUE, "DROPFILES::fWide is set");

  /* Walk the wide list to confirm double-NUL termination. */
  const wchar_t *cursor = reinterpret_cast<const wchar_t *>(base + df->pFiles);
  int walked = 0;
  while (*cursor != L'\0') {
    cursor += wcslen(cursor) + 1;
    walked++;
  }
  check(walked == g_path_count, "list holds exactly the supplied paths");
  check(*(cursor + 1) == L'\0', "list is terminated by a double NUL");
  GlobalUnlock(hdrop);

  char **read_back = nullptr;
  int read_count = 0;
  check(GHOST_DragSourceWin32_ReadHDrop(hdrop, &read_back, &read_count), "ReadHDrop succeeds");
  check(read_count == g_path_count, "ReadHDrop returns the same count");
  for (int i = 0; i < read_count && i < g_path_count; i++) {
    char label[128];
    snprintf(label, sizeof(label), "path %d round-trips (%s)", i, read_back[i]);
    check(strcmp(read_back[i], g_paths[i]) == 0, label);
  }
  GHOST_DragSourceWin32_FreePaths(read_back, read_count);
  GlobalFree(hdrop);
}

static void test_com_object()
{
  printf("com object:\n");

  IDataObject *object = GHOST_DragSourceWin32_CreateDataObject(g_paths, g_path_count);
  check(object != nullptr, "CreateDataObject returns an object");
  if (object == nullptr) {
    return;
  }

  FORMATETC hdrop_format = {CF_HDROP, nullptr, DVASPECT_CONTENT, -1, TYMED_HGLOBAL};
  check(object->QueryGetData(&hdrop_format) == S_OK, "advertises CF_HDROP");

  FORMATETC text_format = {CF_UNICODETEXT, nullptr, DVASPECT_CONTENT, -1, TYMED_HGLOBAL};
  check(object->QueryGetData(&text_format) == DV_E_FORMATETC,
        "does not advertise CF_UNICODETEXT");

  FORMATETC bad_tymed = {CF_HDROP, nullptr, DVASPECT_CONTENT, -1, TYMED_ISTREAM};
  check(object->QueryGetData(&bad_tymed) == DV_E_TYMED, "rejects a storage medium we cannot fill");

  IEnumFORMATETC *enumerator = nullptr;
  check(object->EnumFormatEtc(DATADIR_GET, &enumerator) == S_OK, "EnumFormatEtc succeeds");
  if (enumerator != nullptr) {
    FORMATETC formats[8];
    ULONG fetched = 0;
    enumerator->Next(8, formats, &fetched);
    check(fetched >= 1 && formats[0].cfFormat == CF_HDROP, "first enumerated format is CF_HDROP");
    enumerator->Release();
  }

  STGMEDIUM medium;
  memset(&medium, 0, sizeof(medium));
  check(object->GetData(&hdrop_format, &medium) == S_OK, "GetData(CF_HDROP) succeeds");
  check(medium.tymed == TYMED_HGLOBAL, "GetData hands back an HGLOBAL");

  char **read_back = nullptr;
  int read_count = 0;
  if (GHOST_DragSourceWin32_ReadHDrop(medium.hGlobal, &read_back, &read_count)) {
    bool all_match = read_count == g_path_count;
    for (int i = 0; all_match && i < read_count; i++) {
      all_match = strcmp(read_back[i], g_paths[i]) == 0;
    }
    check(all_match, "GetData payload matches the requested files");
    GHOST_DragSourceWin32_FreePaths(read_back, read_count);
  }
  else {
    check(false, "GetData payload is readable");
  }
  ReleaseStgMedium(&medium);

  IUnknown *unknown = nullptr;
  check(object->QueryInterface(IID_IDropSource, (void **)&unknown) == S_OK,
        "QueryInterface exposes IDropSource");
  if (unknown != nullptr) {
    unknown->Release();
  }

  check(object->QueryInterface(IID_IEnumFORMATETC, (void **)&unknown) == E_NOINTERFACE,
        "QueryInterface refuses interfaces it does not implement");

  object->Release();
}

/**
 * The clipboard half: a copy or cut puts the same `CF_HDROP` payload on the
 * system clipboard, and a paste reads it back.
 *
 * Worth testing here rather than only in the app, because the interesting part
 * is the ownership rule - `SetClipboardData()` takes the handle on success and
 * leaves it to the caller on failure - and a mistake there is a double free or
 * a leak that nothing in the UI would show.
 */
static void test_clipboard()
{
  printf("clipboard:\n");

  check(GHOST_DragSourceWin32_ClipboardSetFiles(g_paths, g_path_count, false) == GHOST_kSuccess,
        "a copy is placed on the clipboard");

  char **paths = nullptr;
  bool move = true;
  const int count = GHOST_DragSourceWin32_ClipboardGetFiles(&paths, &move);
  check(count == g_path_count, "the clipboard reads back the same number of paths");
  check(!move, "a copy is not marked as a move");

  if (count == g_path_count) {
    bool all_match = true;
    for (int i = 0; i < count; i++) {
      if (paths[i] == nullptr || strcmp(paths[i], g_paths[i]) != 0) {
        all_match = false;
        printf("        [%d] got %s\n", i, paths[i] ? paths[i] : "(null)");
      }
    }
    check(all_match, "the paths survive the round trip");
  }
  GHOST_DragSourceWin32_FreePaths(paths, count);

  check(GHOST_DragSourceWin32_ClipboardSetFiles(g_paths, g_path_count, true) == GHOST_kSuccess,
        "a cut is placed on the clipboard");

  paths = nullptr;
  move = false;
  const int cut_count = GHOST_DragSourceWin32_ClipboardGetFiles(&paths, &move);
  check(cut_count == g_path_count, "the cut reads back the same number of paths");
  check(move, "a cut is marked as a move, so pasting elsewhere moves the files");
  GHOST_DragSourceWin32_FreePaths(paths, cut_count);

  check(GHOST_DragSourceWin32_ClipboardSetFiles(nullptr, 0, false) == GHOST_kFailure,
        "an empty file list is rejected");
}

int main()
{
  const HRESULT ole = OleInitialize(nullptr);
  printf("OleInitialize -> 0x%08lX\n", (unsigned long)ole);

  test_payload();
  test_com_object();
  test_clipboard();

  printf("\n%s (%d failure%s)\n",
         g_failures == 0 ? "PASS" : "FAIL",
         g_failures,
         g_failures == 1 ? "" : "s");

  if (SUCCEEDED(ole)) {
    OleUninitialize();
  }
  return g_failures == 0 ? 0 : 1;
}
