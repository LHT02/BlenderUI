/* SPDX-License-Identifier: GPL-2.0-or-later */
/** BLUI filesystem drag targets, separate from Blender's file-picker drop. */

#include "BLI_blenlib.h"
#include "BLI_dynstr.h"
#include "BLI_utildefines.h"
#include "BKE_context.h"
#include "ED_fileselect.h"
#include "ED_screen.h"
#include "MEM_guardedalloc.h"
#include "RNA_access.h"
#include "WM_api.h"
#include "WM_types.h"
#include "file_intern.h"
#include "filelist.h"

static bool destination(bContext *C, const int xy[2], char *path)
{
  SpaceFile *space = CTX_wm_space_file(C);
  ARegion *region = CTX_wm_region(C);
  if (!space || !region || !space->params || !space->files || region->regiontype != RGN_TYPE_WINDOW) {
    return false;
  }
  BLI_strncpy(path, space->params->dir, FILE_MAX);
  if (file_highlight_set(space, region, xy[0], xy[1])) {
    ED_region_tag_redraw(region);
  }
  FileDirEntry *entry = filelist_file(space->files, space->params->highlight_file);
  if (entry) {
    if (!(entry->typeflag & FILE_TYPE_DIR)) {
      return false;
    }
    if (entry->redirection_path) {
      BLI_strncpy(path, entry->redirection_path, FILE_MAX);
    }
    else if (FILENAME_IS_PARENT(entry->relpath)) {
      BLI_path_parent_dir(path);
    }
    else {
      BLI_path_append(path, FILE_MAX, entry->relpath);
    }
  }
  BLI_path_normalize_native(path);
  return true;
}

static bool move_requested(const wmDragPath *data, const char *target, const wmEvent *event)
{
  if (event->modifier & KM_CTRL) {
    return false;
  }
  if (event->modifier & KM_SHIFT) {
    return true;
  }
  /* For internal drags, Explorer's default: move on the same volume, copy
   * across volumes. External drags default to copy unless Shift is held. */
  BLI_stat_t source_stat, target_stat;
  return data->is_internal && BLI_stat(data->path, &source_stat) == 0 &&
         BLI_stat(target, &target_stat) == 0 && source_stat.st_dev == target_stat.st_dev;
}

bool file_blui_drop_poll(bContext *C, wmDrag *drag, const wmEvent *event)
{
  SpaceFile *space = CTX_wm_space_file(C);
  if (drag->type != WM_DRAG_PATH || !space) {
    return false;
  }
  if (space->op) {
    return true;
  }
  char target[FILE_MAX];
  if (!destination(C, event->xy, target)) {
    return false;
  }
  const wmDragPath *data = drag->poin;
  /* The filesystem worker repeats this check using resolved paths, to catch
   * junctions as well. This fast check provides immediate drag feedback. */
  const int count = data->paths_len ? data->paths_len : 1;
  for (int i = 0; i < count; i++) {
    const char *source = data->paths_len ? data->paths[i] : data->path;
    char result[FILE_MAX];
    BLI_path_join(result, sizeof(result), target, BLI_path_basename(source));
    if (BLI_path_cmp(source, result) == 0 || BLI_path_cmp(source, target) == 0) {
      return false;
    }
  }
  return true;
}

void file_blui_drop_copy(bContext *C, wmDrag *drag, wmDropBox *drop)
{
  const wmDragPath *data = drag->poin;
  RNA_string_set(drop->ptr, "filepath", data->path);
  SpaceFile *space = CTX_wm_space_file(C);
  if (space->op) {
    return;
  }
  const wmEvent *event = CTX_wm_window(C)->eventstate;
  char target[FILE_MAX];
  if (!destination(C, event->xy, target)) {
    return;
  }
  RNA_string_set(drop->ptr, "directory", target);
  RNA_boolean_set(drop->ptr, "move", move_requested(data, target, event));
  DynStr *paths = BLI_dynstr_new();
  const int count = data->paths_len ? data->paths_len : 1;
  for (int i = 0; i < count; i++) {
    if (i) {
      BLI_dynstr_append(paths, "\n");
    }
    BLI_dynstr_append(paths, data->paths_len ? data->paths[i] : data->path);
  }
  char *sources = BLI_dynstr_get_cstring(paths);
  RNA_string_set(drop->ptr, "sources", sources);
  MEM_freeN(sources);
  BLI_dynstr_free(paths);
}

char *file_blui_drop_tooltip(bContext *C, wmDrag *drag, const int xy[2], wmDropBox *UNUSED(drop))
{
  SpaceFile *space = CTX_wm_space_file(C);
  char target[FILE_MAX];
  if (space->op || !destination(C, xy, target)) {
    return NULL;
  }
  const wmDragPath *data = drag->poin;
  const bool move = move_requested(data, target, CTX_wm_window(C)->eventstate);
  return BLI_sprintfN("%s %d item(s) to %s  (%s)", move ? "Move" : "Copy",
                      data->paths_len ? data->paths_len : 1, target,
                      move ? "Ctrl: Copy" : "Shift: Move");
}
