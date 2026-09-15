/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/** \file
 * \ingroup GHOST
 *
 * OLE drop source for Windows. See GHOST_DragSourceWin32.hh for why this
 * exists. Deliberately depends on the Windows SDK only, so the payload builder
 * can be compiled and exercised on its own.
 */

#include "GHOST_DragSourceWin32.hh"

#ifdef _WIN32

#  include <cstdlib>
#  include <cstring>
#  include <string>
#  include <vector>

#  include <windows.h>
#  include <ole2.h>
#  include <shlobj.h>

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
  /* `resize`, not `buffer(size_t(len))`: the latter is a function declaration. */
  buffer.resize(size_t(len));
  if (MultiByteToWideChar(CP_UTF8, 0, src, -1, buffer.data(), len) != len) {
    return false;
  }
  /* Drop the terminating NUL that MultiByteToWideChar counted. */
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
/** \name CF_HDROP payload
 * \{ */

void *GHOST_DragSourceWin32_CreateHDrop(const char *const *utf8_paths, int count)
{
  if (utf8_paths == nullptr || count <= 0) {
    return nullptr;
  }

  std::vector<std::wstring> wide;
  wide.reserve(size_t(count));

  size_t bytes = sizeof(DROPFILES);
  for (int i = 0; i < count; i++) {
    std::wstring path;
    if (!utf8_to_utf16(utf8_paths[i], path)) {
      return nullptr;
    }
    bytes += (path.size() + 1) * sizeof(wchar_t);
    wide.push_back(std::move(path));
  }
  /* The list is terminated by an extra NUL, i.e. it ends with two NULs. */
  bytes += sizeof(wchar_t);

  HGLOBAL hglobal = GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, bytes);
  if (hglobal == nullptr) {
    return nullptr;
  }
  void *memory = GlobalLock(hglobal);
  if (memory == nullptr) {
    GlobalFree(hglobal);
    return nullptr;
  }

  DROPFILES *dropfiles = static_cast<DROPFILES *>(memory);
  dropfiles->pFiles = sizeof(DROPFILES);
  dropfiles->fWide = TRUE;
  dropfiles->pt.x = 0;
  dropfiles->pt.y = 0;
  dropfiles->fNC = FALSE;

  wchar_t *cursor = reinterpret_cast<wchar_t *>(static_cast<BYTE *>(memory) + sizeof(DROPFILES));
  for (const std::wstring &path : wide) {
    memcpy(cursor, path.c_str(), path.size() * sizeof(wchar_t));
    cursor += path.size();
    *cursor++ = L'\0';
  }
  *cursor = L'\0';

  GlobalUnlock(hglobal);
  return hglobal;
}

bool GHOST_DragSourceWin32_ReadHDrop(void *hdrop, char ***r_paths, int *r_count)
{
  *r_paths = nullptr;
  *r_count = 0;
  if (hdrop == nullptr) {
    return false;
  }

  HGLOBAL handle = static_cast<HGLOBAL>(hdrop);
  const void *memory = GlobalLock(handle);
  if (memory == nullptr) {
    return false;
  }

  const DROPFILES *dropfiles = static_cast<const DROPFILES *>(memory);
  const BYTE *base = static_cast<const BYTE *>(memory);
  std::vector<std::string> paths;

  if (dropfiles->fWide) {
    const wchar_t *cursor = reinterpret_cast<const wchar_t *>(base + dropfiles->pFiles);
    while (*cursor != L'\0') {
      char *utf8 = nullptr;
      if (!utf16_to_utf8(cursor, &utf8)) {
        GlobalUnlock(handle);
        return false;
      }
      paths.emplace_back(utf8);
      free(utf8);
      cursor += wcslen(cursor) + 1;
    }
  }
  else {
    const char *cursor = reinterpret_cast<const char *>(base + dropfiles->pFiles);
    while (*cursor != '\0') {
      paths.emplace_back(cursor);
      cursor += strlen(cursor) + 1;
    }
  }

  GlobalUnlock(handle);

  char **out = static_cast<char **>(malloc(sizeof(char *) * paths.size()));
  if (out == nullptr) {
    return false;
  }
  for (size_t i = 0; i < paths.size(); i++) {
    out[i] = static_cast<char *>(malloc(paths[i].size() + 1));
    if (out[i] == nullptr) {
      GHOST_DragSourceWin32_FreePaths(out, int(i));
      free(out);
      return false;
    }
    memcpy(out[i], paths[i].c_str(), paths[i].size() + 1);
  }

  *r_paths = out;
  *r_count = int(paths.size());
  return true;
}

void GHOST_DragSourceWin32_FreePaths(char **paths, int count)
{
  if (paths == nullptr) {
    return;
  }
  for (int i = 0; i < count; i++) {
    free(paths[i]);
  }
  free(paths);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Format enumerator
 * \{ */

namespace {

class FormatEnumerator : public IEnumFORMATETC {
 public:
  FormatEnumerator(const FORMATETC *formats, UINT count) : m_index(0), m_ref_count(1)
  {
    m_formats.assign(formats, formats + count);
  }

  HRESULT __stdcall QueryInterface(REFIID riid, void **ppv) override
  {
    if (ppv == nullptr) {
      return E_INVALIDARG;
    }
    *ppv = nullptr;
    if (riid == IID_IUnknown || riid == IID_IEnumFORMATETC) {
      *ppv = static_cast<IEnumFORMATETC *>(this);
      AddRef();
      return S_OK;
    }
    return E_NOINTERFACE;
  }

  ULONG __stdcall AddRef() override
  {
    return ULONG(InterlockedIncrement(&m_ref_count));
  }

  ULONG __stdcall Release() override
  {
    const LONG count = InterlockedDecrement(&m_ref_count);
    if (count == 0) {
      delete this;
    }
    return ULONG(count);
  }

  HRESULT __stdcall Next(ULONG requested, FORMATETC *out, ULONG *fetched) override
  {
    ULONG written = 0;
    while (written < requested && m_index < m_formats.size()) {
      out[written] = m_formats[m_index];
      written++;
      m_index++;
    }
    if (fetched != nullptr) {
      *fetched = written;
    }
    return written == requested ? S_OK : S_FALSE;
  }

  HRESULT __stdcall Skip(ULONG count) override
  {
    m_index += count;
    if (m_index > m_formats.size()) {
      m_index = m_formats.size();
      return S_FALSE;
    }
    return S_OK;
  }

  HRESULT __stdcall Reset() override
  {
    m_index = 0;
    return S_OK;
  }

  HRESULT __stdcall Clone(IEnumFORMATETC **out) override
  {
    if (out == nullptr) {
      return E_INVALIDARG;
    }
    FormatEnumerator *clone = new FormatEnumerator(m_formats.data(), UINT(m_formats.size()));
    clone->m_index = m_index;
    *out = clone;
    return S_OK;
  }

 private:
  std::vector<FORMATETC> m_formats;
  size_t m_index;
  LONG m_ref_count;
};

}  // namespace

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drop source
 * \{ */

namespace {

class DropSource : public IDataObject, public IDropSource {
 public:
  DropSource(const char *const *utf8_paths, int count) : m_ref_count(1)
  {
    m_paths.reserve(size_t(count));
    for (int i = 0; i < count; i++) {
      m_paths.emplace_back(utf8_paths[i]);
    }
    m_preferred_effect_format = RegisterClipboardFormat(CFSTR_PREFERREDDROPEFFECT);
  }

  /* -------------------- IUnknown -------------------- */

  HRESULT __stdcall QueryInterface(REFIID riid, void **ppv) override
  {
    if (ppv == nullptr) {
      return E_INVALIDARG;
    }
    *ppv = nullptr;
    if (riid == IID_IUnknown || riid == IID_IDataObject) {
      *ppv = static_cast<IDataObject *>(this);
    }
    else if (riid == IID_IDropSource) {
      *ppv = static_cast<IDropSource *>(this);
    }
    else {
      return E_NOINTERFACE;
    }
    AddRef();
    return S_OK;
  }

  ULONG __stdcall AddRef() override
  {
    return ULONG(InterlockedIncrement(&m_ref_count));
  }

  ULONG __stdcall Release() override
  {
    const LONG count = InterlockedDecrement(&m_ref_count);
    if (count == 0) {
      delete this;
    }
    return ULONG(count);
  }

  /* -------------------- IDataObject -------------------- */

  HRESULT __stdcall GetData(FORMATETC *format, STGMEDIUM *medium) override
  {
    if (format == nullptr || medium == nullptr) {
      return E_INVALIDARG;
    }
    if ((format->tymed & TYMED_HGLOBAL) == 0) {
      return DV_E_TYMED;
    }
    if (format->dwAspect != DVASPECT_CONTENT) {
      return DV_E_DVASPECT;
    }
    if (format->lindex != -1) {
      return DV_E_LINDEX;
    }

    if (format->cfFormat == CF_HDROP) {
      HGLOBAL hglobal = createHDrop();
      if (hglobal == nullptr) {
        return STG_E_MEDIUMFULL;
      }
      medium->tymed = TYMED_HGLOBAL;
      medium->hGlobal = hglobal;
      medium->pUnkForRelease = nullptr;
      return S_OK;
    }

    if (format->cfFormat == m_preferred_effect_format) {
      HGLOBAL hglobal = GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, sizeof(DWORD));
      if (hglobal == nullptr) {
        return STG_E_MEDIUMFULL;
      }
      DWORD *effect = static_cast<DWORD *>(GlobalLock(hglobal));
      if (effect == nullptr) {
        GlobalFree(hglobal);
        return STG_E_MEDIUMFULL;
      }
      /* Copy is the safe default: never let a drag silently move a user's
       * files out of the folder they were browsing. Holding Shift in Explorer
       * still turns it into a move. */
      *effect = DROPEFFECT_COPY;
      GlobalUnlock(hglobal);

      medium->tymed = TYMED_HGLOBAL;
      medium->hGlobal = hglobal;
      medium->pUnkForRelease = nullptr;
      return S_OK;
    }

    return DV_E_FORMATETC;
  }

  HRESULT __stdcall GetDataHere(FORMATETC *, STGMEDIUM *) override
  {
    return E_NOTIMPL;
  }

  HRESULT __stdcall QueryGetData(FORMATETC *format) override
  {
    if (format == nullptr) {
      return E_INVALIDARG;
    }
    if (format->dwAspect != DVASPECT_CONTENT) {
      return DV_E_DVASPECT;
    }
    if (format->lindex != -1) {
      return DV_E_LINDEX;
    }
    if ((format->tymed & TYMED_HGLOBAL) == 0) {
      return DV_E_TYMED;
    }
    if (format->cfFormat == CF_HDROP || format->cfFormat == m_preferred_effect_format) {
      return S_OK;
    }
    return DV_E_FORMATETC;
  }

  HRESULT __stdcall GetCanonicalFormatEtc(FORMATETC *, FORMATETC *) override
  {
    return E_NOTIMPL;
  }

  HRESULT __stdcall SetData(FORMATETC *, STGMEDIUM *, BOOL) override
  {
    return E_NOTIMPL;
  }

  HRESULT __stdcall EnumFormatEtc(DWORD direction, IEnumFORMATETC **out) override
  {
    if (out == nullptr) {
      return E_INVALIDARG;
    }
    *out = nullptr;
    if (direction != DATADIR_GET) {
      return E_NOTIMPL;
    }

    FORMATETC formats[2];
    formats[0].cfFormat = CF_HDROP;
    formats[0].ptd = nullptr;
    formats[0].dwAspect = DVASPECT_CONTENT;
    formats[0].lindex = -1;
    formats[0].tymed = TYMED_HGLOBAL;

    formats[1] = formats[0];
    formats[1].cfFormat = m_preferred_effect_format;

    *out = new FormatEnumerator(formats, 2);
    return S_OK;
  }

  HRESULT __stdcall DAdvise(FORMATETC *, DWORD, IAdviseSink *, DWORD *) override
  {
    return OLE_E_ADVISENOTSUPPORTED;
  }

  HRESULT __stdcall DUnadvise(DWORD) override
  {
    return OLE_E_ADVISENOTSUPPORTED;
  }

  HRESULT __stdcall EnumDAdvise(IEnumSTATDATA **) override
  {
    return OLE_E_ADVISENOTSUPPORTED;
  }

  /* -------------------- IDropSource -------------------- */

  HRESULT __stdcall QueryContinueDrag(BOOL escape_pressed, DWORD key_state) override
  {
    if (escape_pressed) {
      return DRAGDROP_S_CANCEL;
    }
    /* A left button drag, which is what the file browser starts. */
    if ((key_state & MK_LBUTTON) == 0) {
      return DRAGDROP_S_DROP;
    }
    return S_OK;
  }

  HRESULT __stdcall GiveFeedback(DWORD) override
  {
    return DRAGDROP_S_USEDEFAULTCURSORS;
  }

 private:
  HGLOBAL createHDrop() const
  {
    std::vector<const char *> raw;
    raw.reserve(m_paths.size());
    for (const std::string &path : m_paths) {
      raw.push_back(path.c_str());
    }
    return GHOST_DragSourceWin32_CreateHDrop(raw.data(), int(raw.size()));
  }

  std::vector<std::string> m_paths;
  CLIPFORMAT m_preferred_effect_format;
  LONG m_ref_count;
};

}  // namespace

IDataObject *GHOST_DragSourceWin32_CreateDataObject(const char *const *utf8_paths, int count)
{
  if (utf8_paths == nullptr || count <= 0) {
    return nullptr;
  }
  return static_cast<IDataObject *>(new DropSource(utf8_paths, count));
}

GHOST_TSuccess GHOST_DragSourceWin32_StartDrag(void *hwnd,
                                               const char *const *utf8_paths,
                                               int count)
{
  if (hwnd == nullptr || utf8_paths == nullptr || count <= 0) {
    return GHOST_kFailure;
  }

  DropSource *source = new DropSource(utf8_paths, count);
  DWORD effect = DROPEFFECT_NONE;

  const HRESULT result = DoDragDrop(static_cast<IDataObject *>(source),
                                    static_cast<IDropSource *>(source),
                                    DROPEFFECT_COPY | DROPEFFECT_MOVE | DROPEFFECT_LINK,
                                    &effect);

  source->Release();

  return result == DRAGDROP_S_DROP ? GHOST_kSuccess : GHOST_kFailure;
}

/** \} */

#endif /* _WIN32 */
