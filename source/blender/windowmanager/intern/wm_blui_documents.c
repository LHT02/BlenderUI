/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stddef.h>
/** BLUI document confirmations shared by OS close and workspace/area operators. */
#include "BKE_context.h"
#include "BKE_global.h"
#include "BKE_image.h"
#include "BKE_main.h"
#include "BKE_workspace.h"
#include "BLI_listbase.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"
#include "DNA_image_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_workspace_types.h"
#include "ED_image.h"
#include "RNA_access.h"
#include "WM_api.h"

static bool area_has_document(const ScrArea *area)
{
  LISTBASE_FOREACH (SpaceLink *, space, &area->spacedata) {
    if ((space->spacetype == SPACE_IMAGE && ((SpaceImage *)space)->image) ||
        (space->spacetype == SPACE_TEXT && ((SpaceText *)space)->text))
    {
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

bool WM_blui_document_confirm(bContext *C,
                              const char *action,
                              const char *filepath,
                              const char *workspace)
{
  if (G.background || !CTX_wm_window(C) || !CTX_wm_window(C)->ghostwin ||
      !WM_operatortype_find("WM_OT_blui_document_guard", true))
  {
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
    WorkSpace *target = BLI_findstring(
        &CTX_data_main(C)->workspaces, workspace, offsetof(ID, name) + 2);
    if (target) {
      LISTBASE_FOREACH (WorkSpaceLayout *, layout, &target->layouts) {
        if (screen_has_document(BKE_workspace_layout_screen_get(layout))) {
          needed = true;
          break;
        }
      }
    }
  }
  else if (STREQ(action, "OPEN_IMAGE") || STREQ(action, "NEW_IMAGE") ||
           STREQ(action, "PASTE_IMAGE"))
  {
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

bool WM_blui_document_confirm_dock(bContext *C, const char *arguments)
{
  if (G.background || !CTX_wm_window(C) || !CTX_wm_window(C)->ghostwin || !CTX_wm_area(C) ||
      !area_has_document(CTX_wm_area(C)) ||
      !WM_operatortype_find("WM_OT_blui_document_guard", true))
  {
    return false;
  }
  PointerRNA props;
  WM_operator_properties_create(&props, "WM_OT_blui_document_guard");
  RNA_string_set(&props, "action", "DOCK");
  RNA_string_set(&props, "dock_arguments", arguments);
  WM_operator_name_call(C, "WM_OT_blui_document_guard", WM_OP_INVOKE_DEFAULT, &props, NULL);
  WM_operator_properties_free(&props);
  return true;
}

bool WM_blui_close_moved_window(bContext *C, wmWindow *source, wmWindow *replacement)
{
  if (!WM_operatortype_find("WM_OT_blui_close_moved_window", true)) {
    return false;
  }
  const bScreen *source_screen = WM_window_get_active_screen(source);
  const ScrArea *source_area = source_screen ? source_screen->areabase.first : NULL;
  if (!source_area || !BLI_listbase_is_single(&source_screen->areabase)) {
    return false;
  }
  char from[32], to[32], space[32];
  BLI_snprintf(from, sizeof(from), "%llu", (unsigned long long)(uintptr_t)source);
  BLI_snprintf(to, sizeof(to), "%llu", (unsigned long long)(uintptr_t)replacement);
  BLI_snprintf(
      space, sizeof(space), "%llu", (unsigned long long)(uintptr_t)source_area->spacedata.first);
  PointerRNA props;
  WM_operator_properties_create(&props, "WM_OT_blui_close_moved_window");
  RNA_string_set(&props, "source", from);
  RNA_string_set(&props, "replacement", to);
  RNA_string_set(&props, "source_space", space);
  const int result = WM_operator_name_call(
      C, "WM_OT_blui_close_moved_window", WM_OP_EXEC_DEFAULT, &props, NULL);
  WM_operator_properties_free(&props);
  if (result & OPERATOR_FINISHED) {
    /* Moving a main editor must not recursively close its existing child windows/documents. */
    for (wmWindow *ancestor = replacement->parent; ancestor; ancestor = ancestor->parent) {
      if (ancestor == source) {
        replacement->parent = source->parent;
        break;
      }
    }
    LISTBASE_FOREACH (wmWindow *, window, &CTX_wm_manager(C)->windows) {
      if (window->parent == source) {
        window->parent = replacement;
      }
    }
  }
  return (result & OPERATOR_FINISHED) != 0;
}
