/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2001-2002 NaN Holding BV. All rights reserved. */

/** \file
 * \ingroup bli
 * WIN32-POSIX compatibility layer, MS-Windows-specific functions.
 */

#ifdef WIN32

#  include <conio.h>
#  include <shlwapi.h>
#  include <stdio.h>
#  include <stdlib.h>
#  include <string.h>

#  include "MEM_guardedalloc.h"

#  define WIN32_SKIP_HKEY_PROTECTION /* Need to use HKEY. */
#  include "BLI_fileops.h"
#  include "BLI_path_util.h"
#  include "BLI_string.h"
#  include "BLI_utildefines.h"
#  include "BLI_winstuff.h"

#  include "utf_winfunc.h"
#  include "utfconv.h"

/* FILE_MAXDIR + FILE_MAXFILE */

int BLI_windows_get_executable_dir(char r_dirpath[/*FILE_MAXDIR*/])
{
  char filepath[FILE_MAX];
  char dir[FILE_MAX];
  int a;
  /* Change to utf support. */
  GetModuleFileName(NULL, filepath, sizeof(filepath));
  BLI_path_split_dir_part(filepath, dir, sizeof(dir)); /* shouldn't be relative */
  a = strlen(dir);
  if (dir[a - 1] == '\\') {
    dir[a - 1] = 0;
  }

  BLI_strncpy(r_dirpath, dir, FILE_MAXDIR);

  return 1;
}

static void register_blend_extension_failed(HKEY root, const bool background)
{
  printf("failed\n");
  if (root) {
    RegCloseKey(root);
  }
  if (!background) {
    MessageBox(0, "Could not register file extension.", "BLUI error", MB_OK | MB_ICONERROR);
  }
}

bool BLI_windows_register_blend_extension(const bool background)
{
  LONG lresult;
  HKEY hkey = 0;
  HKEY root = 0;
  BOOL usr_mode = false;
  DWORD dwd = 0;
  char buffer[256];

  char BlPath[MAX_PATH];
  char MBox[256];

  printf("Registering file extension...");
  GetModuleFileName(0, BlPath, MAX_PATH);

  /* Replace the actual app name with the wrapper. */
  {
    char *blender_app = strstr(BlPath, "BLUI.exe");
    if (blender_app != NULL) {
      strcpy(blender_app, "BLUI-launcher.exe");
    }
  }

  /* root is HKLM by default */
  lresult = RegOpenKeyEx(HKEY_LOCAL_MACHINE, "Software\\Classes", 0, KEY_ALL_ACCESS, &root);
  if (lresult != ERROR_SUCCESS) {
    /* try HKCU on failure */
    usr_mode = true;
    lresult = RegOpenKeyEx(HKEY_CURRENT_USER, "Software\\Classes", 0, KEY_ALL_ACCESS, &root);
    if (lresult != ERROR_SUCCESS) {
      register_blend_extension_failed(0, background);
      return false;
    }
  }

  lresult = RegCreateKeyEx(
      root, "blendfile", 0, NULL, REG_OPTION_NON_VOLATILE, KEY_ALL_ACCESS, NULL, &hkey, &dwd);
  if (lresult == ERROR_SUCCESS) {
    strcpy(buffer, "BLUI File");
    lresult = RegSetValueEx(hkey, NULL, 0, REG_SZ, (BYTE *)buffer, strlen(buffer) + 1);
    RegCloseKey(hkey);
  }
  if (lresult != ERROR_SUCCESS) {
    register_blend_extension_failed(root, background);
    return false;
  }

  lresult = RegCreateKeyEx(root,
                           "blendfile\\shell\\open\\command",
                           0,
                           NULL,
                           REG_OPTION_NON_VOLATILE,
                           KEY_ALL_ACCESS,
                           NULL,
                           &hkey,
                           &dwd);
  if (lresult == ERROR_SUCCESS) {
    SNPRINTF(buffer, "\"%s\" \"%%1\"", BlPath);
    lresult = RegSetValueEx(hkey, NULL, 0, REG_SZ, (BYTE *)buffer, strlen(buffer) + 1);
    RegCloseKey(hkey);
  }
  if (lresult != ERROR_SUCCESS) {
    register_blend_extension_failed(root, background);
    return false;
  }

  lresult = RegCreateKeyEx(root,
                           "blendfile\\DefaultIcon",
                           0,
                           NULL,
                           REG_OPTION_NON_VOLATILE,
                           KEY_ALL_ACCESS,
                           NULL,
                           &hkey,
                           &dwd);
  if (lresult == ERROR_SUCCESS) {
    SNPRINTF(buffer, "\"%s\", 1", BlPath);
    lresult = RegSetValueEx(hkey, NULL, 0, REG_SZ, (BYTE *)buffer, strlen(buffer) + 1);
    RegCloseKey(hkey);
  }
  if (lresult != ERROR_SUCCESS) {
    register_blend_extension_failed(root, background);
    return false;
  }

  lresult = RegCreateKeyEx(
      root, ".blend", 0, NULL, REG_OPTION_NON_VOLATILE, KEY_ALL_ACCESS, NULL, &hkey, &dwd);
  if (lresult == ERROR_SUCCESS) {
    strcpy(buffer, "blendfile");
    lresult = RegSetValueEx(hkey, NULL, 0, REG_SZ, (BYTE *)buffer, strlen(buffer) + 1);
    RegCloseKey(hkey);
  }
  if (lresult != ERROR_SUCCESS) {
    register_blend_extension_failed(root, background);
    return false;
  }

#  ifdef WITH_BLENDER_THUMBNAILER
  {
    char RegCmd[MAX_PATH * 2];
    char InstallDir[FILE_MAXDIR];
    char SysDir[FILE_MAXDIR];
    BLI_windows_get_executable_dir(InstallDir);
    GetSystemDirectory(SysDir, FILE_MAXDIR);
    const char *ThumbHandlerDLL = "BlendThumb.dll";
    snprintf(
        RegCmd, MAX_PATH * 2, "%s\\regsvr32 /s \"%s\\%s\"", SysDir, InstallDir, ThumbHandlerDLL);
    system(RegCmd);
  }
#  endif

  RegCloseKey(root);
  printf("success (%s)\n", usr_mode ? "user" : "system");
  if (!background) {
    SNPRINTF(MBox,
             "File extension registered for %s.",
             usr_mode ? "the current user. To register for all users, run as an administrator" :
                        "all users");
    MessageBox(0, MBox, "BLUI", MB_OK | MB_ICONINFORMATION);
  }
  return true;
}

/**
 * Check the registry to see if there is an operation association to a file
 * extension. Extension *should almost always contain a dot like `.txt`,
 * but this does allow querying non - extensions *like "Directory", "Drive",
 * "AllProtocols", etc - anything in Classes with a "shell" branch.
 */
static bool BLI_windows_file_operation_is_registered(const char *extension, const char *operation)
{
  HKEY hKey;
  HRESULT hr = AssocQueryKey(ASSOCF_INIT_IGNOREUNKNOWN,
                             ASSOCKEY_SHELLEXECCLASS,
                             (LPCTSTR)extension,
                             (LPCTSTR)operation,
                             &hKey);
  if (SUCCEEDED(hr)) {
    RegCloseKey(hKey);
    return true;
  }
  return false;
}

bool BLI_windows_external_operation_supported(const char *filepath, const char *operation)
{
  if (STREQ(operation, "open") || STREQ(operation, "properties")) {
    return true;
  }

  if (BLI_is_dir(filepath)) {
    return BLI_windows_file_operation_is_registered("Directory", operation);
  }

  const char *extension = BLI_path_extension(filepath);
  return BLI_windows_file_operation_is_registered(extension, operation);
}

bool BLI_windows_external_operation_execute(const char *filepath, const char *operation)
{
  WCHAR wpath[FILE_MAX];
  if (conv_utf_8_to_16(filepath, wpath, ARRAY_SIZE(wpath)) != 0) {
    return false;
  }

  WCHAR woperation[FILE_MAX];
  if (conv_utf_8_to_16(operation, woperation, ARRAY_SIZE(woperation)) != 0) {
    return false;
  }

  SHELLEXECUTEINFOW shellinfo = {0};
  shellinfo.cbSize = sizeof(SHELLEXECUTEINFO);
  shellinfo.fMask = SEE_MASK_INVOKEIDLIST;
  shellinfo.lpVerb = woperation;
  shellinfo.lpFile = wpath;
  shellinfo.nShow = SW_SHOW;

  return ShellExecuteExW(&shellinfo);
}

bool BLI_windows_file_icon_load(const char *filepath,
                                unsigned char **r_pixels,
                                int *r_width,
                                int *r_height)
{
  if (r_pixels == NULL || r_width == NULL || r_height == NULL) {
    return false;
  }
  *r_pixels = NULL;
  *r_width = 0;
  *r_height = 0;

  WCHAR wpath[FILE_MAX];
  if (conv_utf_8_to_16(filepath, wpath, ARRAY_SIZE(wpath)) != 0) {
    return false;
  }

  /* `SHGFI_ICON` hands back an HICON this function owns and must destroy;
   * `SHGFI_SYSICONINDEX` would instead point into a shared image list. */
  SHFILEINFOW sfi = {0};
  if (SHGetFileInfoW(wpath, 0, &sfi, sizeof(sfi), SHGFI_ICON | SHGFI_LARGEICON) == 0 ||
      sfi.hIcon == NULL)
  {
    return false;
  }

  const int w = GetSystemMetrics(SM_CXICON);
  const int h = GetSystemMetrics(SM_CYICON);

  /* A 32-bit top-down DIB to draw the icon into, so the first row of `bits` is
   * the top of the icon and the bytes come out BGRA. */
  BITMAPV5HEADER bi = {0};
  bi.bV5Size = sizeof(bi);
  bi.bV5Width = w;
  bi.bV5Height = -h;
  bi.bV5Planes = 1;
  bi.bV5BitCount = 32;
  bi.bV5Compression = BI_BITFIELDS;
  bi.bV5RedMask = 0x00FF0000;
  bi.bV5GreenMask = 0x0000FF00;
  bi.bV5BlueMask = 0x000000FF;
  bi.bV5AlphaMask = 0xFF000000;

  HDC screen_dc = GetDC(NULL);
  if (screen_dc == NULL) {
    DestroyIcon(sfi.hIcon);
    return false;
  }

  void *bits = NULL;
  HBITMAP dib = CreateDIBSection(screen_dc, (BITMAPINFO *)&bi, DIB_RGB_COLORS, &bits, NULL, 0);
  HDC mem_dc = CreateCompatibleDC(screen_dc);
  ReleaseDC(NULL, screen_dc);

  if (dib == NULL || mem_dc == NULL || bits == NULL) {
    if (mem_dc != NULL) {
      DeleteDC(mem_dc);
    }
    if (dib != NULL) {
      DeleteObject(dib);
    }
    DestroyIcon(sfi.hIcon);
    return false;
  }

  HGDIOBJ old_bitmap = SelectObject(mem_dc, dib);
  /* Cleared first: a transparent icon leaves its pixels untouched, and an
   * uninitialised DIB would otherwise be drawn as garbage. */
  memset(bits, 0, (size_t)w * (size_t)h * 4);
  DrawIconEx(mem_dc, 0, 0, sfi.hIcon, w, h, 0, NULL, DI_NORMAL);
  SelectObject(mem_dc, old_bitmap);

  DeleteDC(mem_dc);
  DestroyIcon(sfi.hIcon);

  unsigned char *pixels = MEM_mallocN((size_t)w * (size_t)h * 4, __func__);
  const unsigned char *src = (const unsigned char *)bits;
  for (int i = 0, count = w * h; i < count; i++) {
    /* The DIB is BGRA; ImBuf's rect is RGBA. */
    pixels[i * 4 + 0] = src[i * 4 + 2];
    pixels[i * 4 + 1] = src[i * 4 + 1];
    pixels[i * 4 + 2] = src[i * 4 + 0];
    pixels[i * 4 + 3] = src[i * 4 + 3];
  }

  DeleteObject(dib);

  *r_pixels = pixels;
  *r_width = w;
  *r_height = h;
  return true;
}

void BLI_windows_file_icon_free(unsigned char *pixels)
{
  if (pixels != NULL) {
    MEM_freeN(pixels);
  }
}

void BLI_windows_get_default_root_dir(char root[4])
{
  char str[MAX_PATH + 1];

  /* the default drive to resolve a directory without a specified drive
   * should be the Windows installation drive, since this was what the OS
   * assumes. */
  if (GetWindowsDirectory(str, MAX_PATH + 1)) {
    root[0] = str[0];
    root[1] = ':';
    root[2] = '\\';
    root[3] = '\0';
  }
  else {
    /* if GetWindowsDirectory fails, something has probably gone wrong,
     * we are trying the blender install dir though */
    if (GetModuleFileName(NULL, str, MAX_PATH + 1)) {
      printf(
          "Error! Could not get the Windows Directory - "
          "Defaulting to Blender installation Dir!\n");
      root[0] = str[0];
      root[1] = ':';
      root[2] = '\\';
      root[3] = '\0';
    }
    else {
      DWORD tmp;
      int i;
      int rc = 0;
      /* now something has gone really wrong - still trying our best guess */
      printf(
          "Error! Could not get the Windows Directory - "
          "Defaulting to first valid drive! Path might be invalid!\n");
      tmp = GetLogicalDrives();
      for (i = 2; i < 26; i++) {
        if ((tmp >> i) & 1) {
          root[0] = 'a' + i;
          root[1] = ':';
          root[2] = '\\';
          root[3] = '\0';
          if (GetFileAttributes(root) != 0xFFFFFFFF) {
            rc = i;
            break;
          }
        }
      }
      if (0 == rc) {
        printf("ERROR in 'BLI_windows_get_default_root_dir': can't find a valid drive!\n");
        root[0] = 'C';
        root[1] = ':';
        root[2] = '\\';
        root[3] = '\0';
      }
    }
  }
}

#else

/* intentionally empty for UNIX */

#endif
