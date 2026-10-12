/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stddef.h>
/** BLUI document confirmations shared by OS close and workspace/area operators. */
#include "DNA_image_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_workspace_types.h"
#include "BKE_context.h"
#include "BKE_global.h"
#include "BKE_image.h"
#include "BKE_main.h"
#include "BKE_workspace.h"
#include "BLI_listbase.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"
#include "ED_image.h"
#include "RNA_access.h"
#include "WM_api.h"

static bool area_has_document(const ScrArea *area)
{
  LISTBASE_FOREACH (SpaceLink *, space, &area->spacedata) {
    if ((space->spacetype == SPACE_IMAGE && ((SpaceImage *)space)->image) ||
        (space->spacetype == SPACE_TEXT && ((SpaceText *)space)->text)) {
      return true;
    }
  }
  return false;
}

static bool screen_has_document(const bScreen *screen)
{
  if (screen) {
    LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
      if (area_has_document(area)) {
        return true;
      }
    }
  }
  return false;
}

bool WM_blui_document_confirm(bContext *C, const char *action, const char *filepath, const char *workspace)
{
  if (G.background || !CTX_wm_window(C) || !CTX_wm_window(C)->ghostwin ||
      !WM_operatortype_find("WM_OT_blui_document_guard", true)) {
    return false;
  }
  bool needed = false;
  if (STREQ(action, "WINDOW")) {
    wmWindow *target = CTX_wm_window(C);
    LISTBASE_FOREACH (wmWindow *, win, &CTX_wm_manager(C)->windows) {
      wmWindow *ancestor = win;
      while (ancestor && ancestor != target) {
        ancestor = ancestor->parent;
      }
      if (ancestor && screen_has_document(WM_window_get_active_screen(win))) {
        needed = true;
        break;
      }
    }
  }
  else if (STREQ(action, "WORKSPACE")) {
    WorkSpace *target = BLI_findstring(&CTX_data_main(C)->workspaces, workspace, offsetof(ID, name) + 2);
    if (target) {
      LISTBASE_FOREACH (WorkSpaceLayout *, layout, &target->layouts) {
        if (screen_has_document(BKE_workspace_layout_screen_get(layout))) {
          needed = true;
          break;
        }
      }
    }
  }
  else if (STREQ(action, "OPEN_IMAGE") || STREQ(action, "NEW_IMAGE") || STREQ(action, "PASTE_IMAGE")) {
    SpaceImage *space = CTX_wm_space_image(C);
    needed = space && space->image && BKE_image_is_dirty(space->image);
  }
  else {
    ScrArea *area = CTX_wm_area(C);
    needed = area && area_has_document(area);
  }
  if (!needed) {
    return false;
  }
  PointerRNA props;
  WM_operator_properties_create(&props, "WM_OT_blui_document_guard");
  RNA_string_set(&props, "action", action);
  RNA_string_set(&props, "filepath", filepath ? filepath : "");
  RNA_string_set(&props, "workspace", workspace ? workspace : "");
  WM_operator_name_call(C, "WM_OT_blui_document_guard", WM_OP_INVOKE_DEFAULT, &props, NULL);
  WM_operator_properties_free(&props);
  return true;
}

void WM_blui_document_clear_screen(bContext *C, bScreen *screen)
{
  if (!screen) {
    return;
  }
  LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
    LISTBASE_FOREACH (SpaceLink *, space, &area->spacedata) {
      if (space->spacetype == SPACE_IMAGE) {
        ED_image_document_clear(CTX_data_main(C), (SpaceImage *)space);
      }
      else if (space->spacetype == SPACE_TEXT) {
        ((SpaceText *)space)->text = NULL;
      }
    }
  }
}

bool WM_blui_close_moved_window(bContext *C, wmWindow *source, wmWindow *replacement)
{
  if (!WM_operatortype_find("WM_OT_blui_close_moved_window", true)) {
    return false;
  }
  char from[32], to[32];
  BLI_snprintf(from, sizeof(from), "%llu", (unsigned long long)(uintptr_t)source);
  BLI_snprintf(to, sizeof(to), "%llu", (unsigned long long)(uintptr_t)replacement);
  PointerRNA props;
  WM_operator_properties_create(&props, "WM_OT_blui_close_moved_window");
  RNA_string_set(&props, "source", from);
  RNA_string_set(&props, "replacement", to);
  WM_operator_name_call(C, "WM_OT_blui_close_moved_window", WM_OP_EXEC_DEFAULT, &props, NULL);
  WM_operator_properties_free(&props);
  return true;
}
