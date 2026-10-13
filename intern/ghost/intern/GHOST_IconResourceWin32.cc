/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2026 BLUI */
/** Read original icon resources instead of an already-resampled Shell image-list entry. */
#include "GHOST_IconResourceWin32.hh"

#ifdef _WIN32
#  include <algorithm>
#  include <cstdint>
#  include <cstring>
#  include <string>
#  include <vector>

#  include <shlobj.h>
#  include <shlwapi.h>
#  undef min
#  undef max

namespace {
constexpr size_t max_resource_bytes = 8 * 1024 * 1024;

uint16_t word(const unsigned char *bytes)
{
  return uint16_t(bytes[0]) | (uint16_t(bytes[1]) << 8);
}

uint32_t dword(const unsigned char *bytes)
{
  return uint32_t(word(bytes)) | (uint32_t(word(bytes + 2)) << 16);
}

uint32_t png_dword(const unsigned char *bytes)
{
  return (uint32_t(bytes[0]) << 24) | (uint32_t(bytes[1]) << 16) | (uint32_t(bytes[2]) << 8) |
         uint32_t(bytes[3]);
}

HICON create_icon(const unsigned char *bytes, const size_t size)
{
  if (size < 40 || size > max_resource_bytes) {
    return nullptr;
  }
  /* Validate the actual dimensions, not just the (untrusted) directory entry. */
  const unsigned char png_signature[] = {137, 80, 78, 71, 13, 10, 26, 10};
  uint32_t width = 0, height = 0;
  if (memcmp(bytes, png_signature, sizeof(png_signature)) == 0) {
    if (memcmp(bytes + 12, "IHDR", 4) != 0) {
      return nullptr;
    }
    width = png_dword(bytes + 16);
    height = png_dword(bytes + 20);
  }
  else if (dword(bytes) >= 40 && dword(bytes) <= size) {
    width = dword(bytes + 4);
    /* DIB resources include the color bitmap followed by its AND mask. */
    height = dword(bytes + 8) / 2;
  }
  if (!width || !height || width > 1024 || height > 1024) {
    return nullptr;
  }
  /* Zero desired dimensions + no LR_DEFAULTSIZE preserves the resource's intrinsic size. */
  return CreateIconFromResourceEx(
      const_cast<unsigned char *>(bytes), DWORD(size), TRUE, 0x00030000, 0, 0, LR_DEFAULTCOLOR);
}

std::vector<size_t> ranked_entries(const unsigned char *bytes,
                                   const size_t size,
                                   const size_t entry_size)
{
  std::vector<size_t> entries;
  if (size < 6 || word(bytes) != 0 || word(bytes + 2) != 1) {
    return entries;
  }
  const size_t count = word(bytes + 4);
  if (!count || count > 1024 || count > (size - 6) / entry_size) {
    return entries;
  }
  for (size_t i = 0; i < count; i++) {
    entries.push_back(6 + i * entry_size);
  }
  std::stable_sort(entries.begin(), entries.end(), [bytes](const size_t a, const size_t b) {
    const int area_a = (bytes[a] ? bytes[a] : 256) * (bytes[a + 1] ? bytes[a + 1] : 256);
    const int area_b = (bytes[b] ? bytes[b] : 256) * (bytes[b + 1] ? bytes[b + 1] : 256);
    return area_a != area_b ? area_a > area_b : word(bytes + a + 6) > word(bytes + b + 6);
  });
  return entries;
}

HICON load_ico(const wchar_t *path)
{
  HANDLE file = CreateFileW(path,
                            GENERIC_READ,
                            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                            nullptr,
                            OPEN_EXISTING,
                            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN,
                            nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    return nullptr;
  }
  LARGE_INTEGER length = {};
  std::vector<unsigned char> bytes;
  DWORD read = 0;
  if (GetFileSizeEx(file, &length) && length.QuadPart >= 6 && length.QuadPart <= 16 * 1024 * 1024)
  {
    bytes.resize(size_t(length.QuadPart));
    if (!ReadFile(file, bytes.data(), DWORD(bytes.size()), &read, nullptr) || read != bytes.size())
    {
      bytes.clear();
    }
  }
  CloseHandle(file);
  for (const size_t entry : ranked_entries(bytes.data(), bytes.size(), 16)) {
    const size_t size = dword(bytes.data() + entry + 8);
    const size_t offset = dword(bytes.data() + entry + 12);
    if (offset <= bytes.size() && size <= bytes.size() - offset) {
      if (HICON icon = create_icon(bytes.data() + offset, size)) {
        return icon;
      }
    }
  }
  return nullptr;
}

struct GroupSelector {
  int remaining;
  WORD resource_id = 0;
  std::wstring name;
  bool found = false;
};

BOOL CALLBACK select_group(HMODULE, LPCWSTR, LPWSTR name, LONG_PTR data)
{
  auto &selector = *reinterpret_cast<GroupSelector *>(data);
  if (selector.remaining-- == 0) {
    selector.found = true;
    if (IS_INTRESOURCE(name)) {
      selector.resource_id = WORD(reinterpret_cast<ULONG_PTR>(name));
    }
    else {
      selector.name = name;
    }
    return FALSE;
  }
  return TRUE;
}

HICON load_pe(const wchar_t *path, const int index)
{
  /* Data-only mapping: never run DllMain, imports, or code from a shortcut's icon provider. */
  HMODULE module = LoadLibraryExW(
      path, nullptr, LOAD_LIBRARY_AS_DATAFILE_EXCLUSIVE | LOAD_LIBRARY_AS_IMAGE_RESOURCE);
  if (!module) {
    return nullptr;
  }
  GroupSelector selector = {index};
  LPCWSTR name = nullptr;
  if (index < 0 && index >= -65535) {
    name = MAKEINTRESOURCEW(-index);
  }
  else if (index >= 0) {
    EnumResourceNamesW(
        module, MAKEINTRESOURCEW(14), select_group, reinterpret_cast<LONG_PTR>(&selector));
    if (selector.found) {
      name = selector.name.empty() ? MAKEINTRESOURCEW(selector.resource_id) :
                                     selector.name.c_str();
    }
  }
  HICON icon = nullptr;
  const HRSRC group = name ? FindResourceW(module, name, MAKEINTRESOURCEW(14)) : nullptr;
  const size_t group_size = group ? SizeofResource(module, group) : 0;
  const auto *directory = group_size ? static_cast<const unsigned char *>(
                                           LockResource(LoadResource(module, group))) :
                                       nullptr;
  if (directory && group_size <= max_resource_bytes) {
    for (const size_t entry : ranked_entries(directory, group_size, 14)) {
      const HRSRC resource = FindResourceW(
          module, MAKEINTRESOURCEW(word(directory + entry + 12)), MAKEINTRESOURCEW(3));
      const size_t size = resource ? SizeofResource(module, resource) : 0;
      const auto *bytes = size ? static_cast<const unsigned char *>(
                                     LockResource(LoadResource(module, resource))) :
                                 nullptr;
      if (bytes && (icon = create_icon(bytes, size))) {
        break;
      }
    }
  }
  FreeLibrary(module);
  return icon;
}

std::wstring absolute_icon_path(const wchar_t *link, const wchar_t *location)
{
  const DWORD size = ExpandEnvironmentStringsW(location, nullptr, 0);
  if (!size || size > 32768) {
    return {};
  }
  std::wstring path(size, L'\0');
  if (!ExpandEnvironmentStringsW(location, path.data(), size)) {
    return {};
  }
  path.resize(wcslen(path.c_str()));
  if (path.size() >= 2 && path.front() == L'"' && path.back() == L'"') {
    path = path.substr(1, path.size() - 2);
  }
  if (path.empty()) {
    return {};
  }
  if (PathIsRelativeW(path.c_str())) {
    const std::wstring shortcut = link;
    const size_t slash = shortcut.find_last_of(L"/\\");
    if (slash == std::wstring::npos) {
      return {};
    }
    path = shortcut.substr(0, slash + 1) + path;
  }
  return path;
}
}  // namespace

HICON GHOST_Win32_LoadShortcutIconResource(const wchar_t *path)
{
  if (!path || _wcsicmp(PathFindExtensionW(path), L".lnk") != 0) {
    return nullptr;
  }
  IShellLinkW *link = nullptr;
  if (FAILED(CoCreateInstance(CLSID_ShellLink,
                              nullptr,
                              CLSCTX_INPROC_SERVER,
                              IID_IShellLinkW,
                              reinterpret_cast<void **>(&link))))
  {
    return nullptr;
  }
  IPersistFile *file = nullptr;
  HICON icon = nullptr;
  if (SUCCEEDED(link->QueryInterface(IID_IPersistFile, reinterpret_cast<void **>(&file)))) {
    if (SUCCEEDED(file->Load(path, STGM_READ))) {
      std::vector<wchar_t> location(32768, L'\0');
      int index = 0;
      if (FAILED(link->GetIconLocation(location.data(), int(location.size()), &index))) {
        location[0] = L'\0';
      }
      if (!location[0]) {
        /* No Resolve(): do not search disconnected drives, repair links, or ask for credentials.
         */
        link->GetPath(location.data(), int(location.size()), nullptr, SLGP_RAWPATH);
        index = 0;
      }
      const std::wstring resource = absolute_icon_path(path, location.data());
      if (!resource.empty() && !PathIsUNCW(resource.c_str())) {
        icon = _wcsicmp(PathFindExtensionW(resource.c_str()), L".ico") == 0 ?
                   load_ico(resource.c_str()) :
                   load_pe(resource.c_str(), index);
      }
    }
    file->Release();
  }
  link->Release();
  return icon;
}
#endif
