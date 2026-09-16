/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/**
 * Load ONE shell context-menu handler and time its `QueryContextMenu`.
 *
 * BLUI's shell menu hangs, and the phase timings say it hangs inside
 * `QueryContextMenu` - where every handler registered for the item gets to run.
 * Nothing in that call says which one failed to return, so this takes them one
 * at a time: give it a path and a CLSID, and the process either prints a time or
 * never comes back. The driver (`probe_shellmenu_handlers.ps1`) runs one of
 * these per handler with a timeout, so a hang names the extension instead of
 * stalling the whole investigation.
 *
 * Usage:
 *   shellmenu_handler_probe.exe <path> <clsid>
 *
 * Exits 0 when the handler returned, 2 when it could not be loaded at all
 * (which is normal - most CLSIDs are registered for other item types).
 */

#include <cstdio>
#include <cstring>
#include <string>

#include <windows.h>
#include <ole2.h>
#include <shlobj.h>
#include <shlwapi.h>

/* This file builds against the SDK alone, so it cannot use BLI's ARRAY_SIZE. */
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))

static void print_hr(const char *what, HRESULT hr)
{
  printf("    %-22s hr=0x%08lX\n", what, (unsigned long)hr);
}

int main(int argc, char **argv)
{
  if (argc < 3) {
    printf("usage: shellmenu_handler_probe.exe <path> <clsid>\n");
    return 3;
  }

  const char *path = argv[1];
  const char *clsid_text = argv[2];

  CLSID clsid;
  {
    wchar_t wide_clsid[64];
    if (MultiByteToWideChar(CP_UTF8, 0, clsid_text, -1, wide_clsid, ARRAY_SIZE(wide_clsid)) == 0) {
      printf("  bad clsid %s\n", clsid_text);
      return 3;
    }
    if (FAILED(CLSIDFromString(wide_clsid, &clsid))) {
      printf("  bad clsid %s\n", clsid_text);
      return 3;
    }
  }

  const HRESULT ole = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

  /* Path -> absolute pidl, then split into the parent folder and the child. */
  wchar_t wide_path[MAX_PATH];
  if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wide_path, ARRAY_SIZE(wide_path)) == 0) {
    printf("  cannot read path %s\n", path);
    return 3;
  }
  PIDLIST_ABSOLUTE pidl = nullptr;
  if (FAILED(SHParseDisplayName(wide_path, nullptr, &pidl, 0, nullptr)) || pidl == nullptr) {
    printf("  cannot parse %s\n", path);
    return 3;
  }
  PIDLIST_ABSOLUTE parent = ILClone(pidl);
  ILRemoveLastID(parent);
  PCUITEMID_CHILD child = ILFindLastID(pidl);

  IShellExtInit *init = nullptr;
  HRESULT hr = CoCreateInstance(clsid, nullptr, CLSCTX_INPROC_SERVER, IID_IShellExtInit,
                                reinterpret_cast<void **>(&init));
  if (FAILED(hr) || init == nullptr) {
    /* Not an IShellExtInit, or not for this item type. Not a failure. */
    print_hr("CoCreateInstance", hr);
    return 2;
  }

  IDataObject *data_object = nullptr;
  hr = SHCreateDataObject(parent, 1, &child, nullptr, IID_IDataObject,
                          reinterpret_cast<void **>(&data_object));
  if (FAILED(hr) || data_object == nullptr) {
    print_hr("SHCreateDataObject", hr);
    init->Release();
    return 2;
  }

  printf("  Initialize...\n");
  fflush(stdout);
  const ULONGLONG t_init = GetTickCount64();
  hr = init->Initialize(parent, data_object, nullptr);
  printf("  Initialize             %llu ms (hr=0x%08lX)\n",
         GetTickCount64() - t_init,
         (unsigned long)hr);
  fflush(stdout);

  IContextMenu *menu = nullptr;
  hr = init->QueryInterface(IID_IContextMenu, reinterpret_cast<void **>(&menu));
  if (FAILED(hr) || menu == nullptr) {
    print_hr("QueryInterface", hr);
    data_object->Release();
    init->Release();
    return 2;
  }

  HMENU hmenu = CreatePopupMenu();
  printf("  QueryContextMenu...\n");
  fflush(stdout);
  const ULONGLONG t_qcm = GetTickCount64();
  hr = menu->QueryContextMenu(hmenu, 0, 1, 0x7FFF, CMF_NORMAL);
  const ULONGLONG elapsed = GetTickCount64() - t_qcm;
  printf("  QueryContextMenu       %llu ms (hr=0x%08lX, items=%d)\n",
         elapsed,
         (unsigned long)hr,
         (int)GetMenuItemCount(hmenu));
  fflush(stdout);

  DestroyMenu(hmenu);
  menu->Release();
  data_object->Release();
  init->Release();
  ILFree(parent);
  ILFree(pidl);
  if (SUCCEEDED(ole)) {
    CoUninitialize();
  }
  return 0;
}
