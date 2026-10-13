/* SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * Disposable desktop preview entry point. Uses the File Browser's ImBuf thumbnail pipeline,
 * without opening a window, loading Python, preferences, startup files, or executable file data.
 */

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#ifdef WIN32
#  include <windows.h>
#  include "utfconv.h"
#endif

#include "BKE_blendfile.h"
#include "BLI_fileops.h"
#include "BLI_path_util.h"
#include "DNA_space_types.h"
#include "ED_fileselect.h"
#include "IMB_imbuf.h"
#include "IMB_imbuf_types.h"
#include "IMB_thumbs.h"

#include "creator_intern.h"

#ifdef WIN32
static DWORD WINAPI preview_watchdog(void *)
{
  /* Independent of the Python parent: cancellation cannot leave a wedged grandchild behind. */
  Sleep(3000);
  TerminateProcess(GetCurrentProcess(), 124);
  return 0;
}
#endif

void main_blui_file_preview_prepare(void)
{
#ifdef WIN32
  SetPriorityClass(GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS);
  HANDLE thread = CreateThread(nullptr, 0, preview_watchdog, nullptr, 0, nullptr);
  if (!thread) {
    /* Refuse decoding if the last-resort deadline cannot be installed. */
    ExitProcess(125);
  }
  CloseHandle(thread);
  HANDLE job = CreateJobObjectW(nullptr, nullptr);
  if (job) {
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = {};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY;
    limits.ProcessMemoryLimit = size_t(768) * 1024 * 1024;
    if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits)) ||
        !AssignProcessToJobObject(job, GetCurrentProcess()))
    {
      CloseHandle(job);
    }
    /* Keep an assigned job handle for this short-lived process. The OS releases it on exit. */
  }
#endif
}

static bool preview_source(const char *path, ThumbSource *r_source)
{
  char blend_path[FILE_MAX_LIBEXTRA];
  char *group = nullptr, *id = nullptr;
  if (BKE_blendfile_library_path_explode(path, blend_path, &group, &id)) {
    *r_source = THB_SOURCE_BLEND;
    return true;
  }
  const int type = ED_path_extension_type(path);
  if (type & FILE_TYPE_IMAGE) {
    *r_source = THB_SOURCE_IMAGE;
  }
  else if (type & (FILE_TYPE_BLENDER | FILE_TYPE_BLENDER_BACKUP | FILE_TYPE_BLENDERLIB)) {
    *r_source = THB_SOURCE_BLEND;
  }
  else if (type & FILE_TYPE_MOVIE) {
    *r_source = THB_SOURCE_MOVIE;
  }
  else if (type & FILE_TYPE_FTFONT) {
    *r_source = THB_SOURCE_FONT;
  }
  else {
    return false;
  }
  return true;
}

int main_blui_file_preview(const char *filepath, const char *result_path)
{
  /* Native thumbnail helpers use fixed FILE_MAX buffers. Do not truncate long paths. */
  if (!filepath || !result_path || !filepath[0] || !result_path[0] ||
      strlen(filepath) >= FILE_MAX || strlen(result_path) >= FILE_MAX ||
      !BLI_path_is_abs_from_cwd(filepath) || !BLI_path_is_abs_from_cwd(result_path))
  {
    return 2;
  }
  bool offline = false;
#ifdef WIN32
  char blend_path[FILE_MAX_LIBEXTRA];
  char *group = nullptr, *id = nullptr;
  const char *attribute_path = BKE_blendfile_library_path_explode(filepath, blend_path, &group, &id) ?
                                   blend_path : filepath;
  wchar_t *wide_path = alloc_utf16_from_8(attribute_path, 0);
  if (!wide_path) {
    return 2;
  }
  const DWORD attributes = GetFileAttributesW(wide_path);
  free(wide_path);
  if (attributes != INVALID_FILE_ATTRIBUTES) {
    if (attributes & FILE_ATTRIBUTE_DIRECTORY) {
      return 3;
    }
    /* Match File Browser: a cloud placeholder must never be hydrated just for a preview. */
    offline = (attributes & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN |
                             FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)) != 0;
  }
#endif

  ThumbSource source = THB_SOURCE_IMAGE;
  if (!offline) {
#ifdef WITH_FFMPEG
    /* ED_path_extension_type probes .ogg's video/audio type, just like File Browser. */
    IMB_ffmpeg_init();
#endif
    /* In particular, never run the content-based .ogg probe on an offline placeholder. */
    if (!preview_source(filepath, &source)) {
      return 3;
    }
  }

  IMB_thumb_makedirs();
  ImBuf *image = offline ? IMB_thumb_read(filepath, THB_LARGE) :
                          IMB_thumb_manage(filepath, THB_LARGE, source);
  if (!image) {
    return 3;
  }
  if (image->x > PREVIEW_RENDER_LARGE_HEIGHT || image->y > PREVIEW_RENDER_LARGE_HEIGHT) {
    const float scale = float(PREVIEW_RENDER_LARGE_HEIGHT) /
                        float(image->x > image->y ? image->x : image->y);
    IMB_scaleImBuf(image, int(image->x * scale) > 0 ? int(image->x * scale) : 1,
                  int(image->y * scale) > 0 ? int(image->y * scale) : 1);
  }
  if (!image->rect || image->x <= 0 || image->y <= 0) {
    IMB_freeImBuf(image);
    return 3;
  }
  FILE *output = BLI_fopen(result_path, "wb");
  if (!output) {
    IMB_freeImBuf(image);
    return 4;
  }
  const uint32_t dimensions[2] = {uint32_t(image->x), uint32_t(image->y)};
  bool success = fwrite("BTP1", 1, 4, output) == 4 &&
                 fwrite(dimensions, sizeof(uint32_t), 2, output) == 2;
  const size_t stride = size_t(image->x) * 4;
  /* ImBuf is bottom-up; the bounded mailbox protocol is top-down, like the icon helper. */
  for (int row = image->y - 1; success && row >= 0; row--) {
    success = fwrite(reinterpret_cast<const unsigned char *>(image->rect) + size_t(row) * stride,
                     1, stride, output) == stride;
  }
  success = fclose(output) == 0 && success;
  IMB_freeImBuf(image);
  return success ? 0 : 4;
}
