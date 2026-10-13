/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2026 BLUI */
/** Windows file icons: prefer actual detail, not a padded jumbo bitmap. */
#include "GHOST_IconResourceWin32.hh"
#include "GHOST_ShellMenuWin32.hh"

#ifdef _WIN32
#  include <algorithm>
#  include <cstdlib>
#  include <cstring>
#  include <string>
#  include <utility>
#  include <vector>

/* Windows types must be available before the Shell and common-controls headers. */
#  include <windows.h>

#  include <commctrl.h>
#  include <commoncontrols.h>
#  include <shlobj.h>
#  include <shlwapi.h>
#  undef min
#  undef max

namespace {
struct IconPixels {
  int width = 0, height = 0;
  int xmin = 0, ymin = 0, xmax = 0, ymax = 0;
  std::vector<unsigned char> bgra;
  int visible_size() const
  {
    return bgra.empty() ? 0 : std::max(xmax - xmin + 1, ymax - ymin + 1);
  }
};

bool read_icon(HICON icon, IconPixels &image)
{
  ICONINFO info = {};
  if (!GetIconInfo(icon, &info)) {
    return false;
  }
  BITMAP bitmap = {};
  bool color = info.hbmColor != nullptr;
  bool valid = GetObjectW(color ? info.hbmColor : info.hbmMask, sizeof(bitmap), &bitmap) != 0;
  image.width = bitmap.bmWidth;
  image.height = color ? bitmap.bmHeight : bitmap.bmHeight / 2;
  valid = valid && image.width > 0 && image.height > 0 && image.width <= 1024 &&
          image.height <= 1024;
  HDC screen = valid ? GetDC(nullptr) : nullptr;
  HDC memory = screen ? CreateCompatibleDC(screen) : nullptr;
  void *bits = nullptr;
  BITMAPV5HEADER header = {};
  header.bV5Size = sizeof(header);
  header.bV5Width = image.width;
  header.bV5Height = -image.height;
  header.bV5Planes = 1;
  header.bV5BitCount = 32;
  header.bV5Compression = BI_BITFIELDS;
  header.bV5RedMask = 0x00ff0000;
  header.bV5GreenMask = 0x0000ff00;
  header.bV5BlueMask = 0x000000ff;
  header.bV5AlphaMask = 0xff000000;
  HBITMAP dib = memory ? CreateDIBSection(screen,
                                          reinterpret_cast<BITMAPINFO *>(&header),
                                          DIB_RGB_COLORS,
                                          &bits,
                                          nullptr,
                                          0) :
                         nullptr;
  valid = valid && memory && dib && bits;
  if (valid) {
    HGDIOBJ previous = SelectObject(memory, dib);
    const size_t bytes = size_t(image.width) * image.height * 4;
    memset(bits, 0, bytes);
    valid = DrawIconEx(memory, 0, 0, icon, image.width, image.height, 0, nullptr, DI_NORMAL);
    SelectObject(memory, previous);
    if (valid) {
      const auto *pixels = static_cast<const unsigned char *>(bits);
      image.bgra.assign(pixels, pixels + bytes);
      bool has_alpha = false;
      for (size_t i = 3; i < bytes; i += 4) {
        has_alpha |= image.bgra[i] != 0;
      }
      /* Legacy icons use an AND mask instead of a 32-bit alpha channel. */
      if (!has_alpha && info.hbmMask) {
        BITMAP mask_bitmap = {};
        GetObjectW(info.hbmMask, sizeof(mask_bitmap), &mask_bitmap);
        BITMAPINFO mask_info = {};
        mask_info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
        mask_info.bmiHeader.biWidth = image.width;
        mask_info.bmiHeader.biHeight = -mask_bitmap.bmHeight;
        mask_info.bmiHeader.biPlanes = 1;
        mask_info.bmiHeader.biBitCount = 32;
        mask_info.bmiHeader.biCompression = BI_RGB;
        std::vector<unsigned char> mask(bytes);
        if (GetDIBits(
                memory, info.hbmMask, 0, image.height, mask.data(), &mask_info, DIB_RGB_COLORS))
        {
          for (size_t i = 0; i < bytes; i += 4) {
            image.bgra[i + 3] = mask[i] ? 0 : 255;
          }
        }
      }
      image.xmin = image.width;
      image.ymin = image.height;
      image.xmax = image.ymax = -1;
      for (int y = 0; y < image.height; y++) {
        for (int x = 0; x < image.width; x++) {
          if (image.bgra[(size_t(y) * image.width + x) * 4 + 3] >= 8) {
            image.xmin = std::min(image.xmin, x);
            image.ymin = std::min(image.ymin, y);
            image.xmax = std::max(image.xmax, x);
            image.ymax = std::max(image.ymax, y);
          }
        }
      }
      valid = image.xmax >= image.xmin && image.ymax >= image.ymin;
    }
  }
  if (dib) {
    DeleteObject(dib);
  }
  if (memory) {
    DeleteDC(memory);
  }
  if (screen) {
    ReleaseDC(nullptr, screen);
  }
  if (info.hbmColor) {
    DeleteObject(info.hbmColor);
  }
  if (info.hbmMask) {
    DeleteObject(info.hbmMask);
  }
  return valid;
}
}  // namespace

bool GHOST_ShellMenuWin32_LoadFileIconRgba(const char *path,
                                           unsigned char **r_pixels,
                                           int *r_width,
                                           int *r_height)
{
  if (!path || !r_pixels || !r_width || !r_height) {
    return false;
  }
  *r_pixels = nullptr;
  *r_width = *r_height = 0;
  struct Apartment {
    HRESULT result = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    ~Apartment()
    {
      if (SUCCEEDED(result)) {
        CoUninitialize();
      }
    }
  } apartment;
  const int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, nullptr, 0);
  if (!length) {
    return false;
  }
  std::wstring wide(size_t(length), L'\0');
  if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide.data(), length)) {
    return false;
  }
  IconPixels best;
  if (HICON icon = GHOST_Win32_LoadShortcutIconResource(wide.c_str())) {
    IconPixels candidate;
    if (read_icon(icon, candidate)) {
      best = std::move(candidate);
    }
    DestroyIcon(icon);
  }
  SHFILEINFOW file = {};
  /* Original resources keep fine detail that Shell cache entries may already have discarded.
   * Preserve the image-list path for folders, associations, broken links, and virtual targets. */
  if (best.bgra.empty()) {
    DWORD_PTR got = SHGetFileInfoW(wide.c_str(), 0, &file, sizeof(file), SHGFI_SYSICONINDEX);
    if (!got) {
      const DWORD attributes = PathIsDirectoryW(wide.c_str()) ? FILE_ATTRIBUTE_DIRECTORY :
                                                                FILE_ATTRIBUTE_NORMAL;
      got = SHGetFileInfoW(wide.c_str(),
                           attributes,
                           &file,
                           sizeof(file),
                           SHGFI_SYSICONINDEX | SHGFI_USEFILEATTRIBUTES);
    }
    if (!got) {
      return false;
    }
    for (const int tier : {SHIL_JUMBO, SHIL_EXTRALARGE, SHIL_LARGE, SHIL_SMALL}) {
      IImageList *list = nullptr;
      if (FAILED(SHGetImageList(tier, IID_IImageList, reinterpret_cast<void **>(&list))) || !list)
      {
        continue;
      }
      HICON icon = nullptr;
      list->GetIcon(file.iIcon, ILD_TRANSPARENT, &icon);
      list->Release();
      if (!icon) {
        continue;
      }
      IconPixels candidate;
      if (read_icon(icon, candidate) && candidate.visible_size() > best.visible_size()) {
        best = std::move(candidate);
      }
      DestroyIcon(icon);
    }
  }
  if (best.bgra.empty()) {
    return false;
  }
  int xmin = 0, ymin = 0, xmax = best.width - 1, ymax = best.height - 1;
  if (std::max(best.width, best.height) >= 128 &&
      best.visible_size() <= std::max(best.width, best.height) / 2)
  {
    /* Some jumbo entries contain only a 16/32px icon in a 256px transparent canvas. */
    const int margin = std::max(2, best.visible_size() / 16);
    xmin = std::max(0, best.xmin - margin);
    ymin = std::max(0, best.ymin - margin);
    xmax = std::min(best.width - 1, best.xmax + margin);
    ymax = std::min(best.height - 1, best.ymax + margin);
  }
  const int width = xmax - xmin + 1, height = ymax - ymin + 1;
  auto *pixels = static_cast<unsigned char *>(malloc(size_t(width) * height * 4));
  if (!pixels) {
    return false;
  }
  for (int y = 0; y < height; y++) {
    for (int x = 0; x < width; x++) {
      const size_t from = (size_t(y + ymin) * best.width + x + xmin) * 4;
      const size_t to = (size_t(y) * width + x) * 4;
      const unsigned int alpha = best.bgra[from + 3];
      /* DrawIconEx produces premultiplied pixels. File-browser image previews use straight
       * alpha: undo that multiplication once so antialiased edges do not become dark halos. */
      for (int channel = 0; channel < 3; channel++) {
        const unsigned int color = best.bgra[from + 2 - channel];
        pixels[to + channel] = alpha ? std::min(255u, (color * 255 + alpha / 2) / alpha) : 0;
      }
      pixels[to + 3] = alpha;
    }
  }
  *r_pixels = pixels;
  *r_width = width;
  *r_height = height;
  return true;
}

void GHOST_ShellMenuWin32_FreeIconRgba(unsigned char *pixels)
{
  free(pixels);
}
#endif
