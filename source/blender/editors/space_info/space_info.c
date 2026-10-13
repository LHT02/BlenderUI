/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2008 Blender Foundation */

/** \file
 * \ingroup spinfo
 */

#include <stdio.h>
#include <string.h>

#include "MEM_guardedalloc.h"

#include "BLI_blenlib.h"
#include "BLI_utildefines.h"

#include "BKE_context.h"
#include "BKE_screen.h"

#include "ED_screen.h"
#include "ED_space_api.h"

#include "WM_api.h"
#include "WM_message.h"
#include "WM_types.h"

#include "RNA_access.h"

#include "UI_interface.h"
#include "UI_resources.h"
#include "UI_view2d.h"

#include "BLO_read_write.h"
#include "DNA_windowmanager_types.h"

#include "info_intern.h" /* own include */

/* ******************** default callbacks for info space ***************** */

static SpaceLink *info_create(const ScrArea *UNUSED(area), const Scene *UNUSED(scene))
{
  ARegion *region;
  SpaceInfo *sinfo;

  sinfo = MEM_callocN(sizeof(SpaceInfo), "initinfo");
  sinfo->spacetype = SPACE_INFO;

  sinfo->rpt_mask = INFO_RPT_OP;

  /* header */
  region = MEM_callocN(sizeof(ARegion), "header for info");

  BLI_addtail(&sinfo->regionbase, region);
  region->regiontype = RGN_TYPE_HEADER;
  region->alignment = (U.uiflag & USER_HEADER_BOTTOM) ? RGN_ALIGN_BOTTOM : RGN_ALIGN_TOP;

  /* main region */
  region = MEM_callocN(sizeof(ARegion), "main region for info");

  BLI_addtail(&sinfo->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  /* keep in sync with console */
  region->v2d.scroll |= V2D_SCROLL_RIGHT;
  region->v2d.align |= V2D_ALIGN_NO_NEG_X | V2D_ALIGN_NO_NEG_Y; /* align bottom left */
  region->v2d.keepofs |= V2D_LOCKOFS_X;
  region->v2d.keepzoom = (V2D_LOCKZOOM_X | V2D_LOCKZOOM_Y | V2D_LIMITZOOM | V2D_KEEPASPECT);
  region->v2d.keeptot = V2D_KEEPTOT_BOUNDS;
  region->v2d.minzoom = region->v2d.maxzoom = 1.0f;

  /* for now, aspect ratio should be maintained, and zoom is clamped within sane default limits */
  // region->v2d.keepzoom = (V2D_KEEPASPECT|V2D_LIMITZOOM);

  return (SpaceLink *)sinfo;
}

/* not spacelink itself */
static void info_free(SpaceLink *UNUSED(sl))
{
  //  SpaceInfo *sinfo = (SpaceInfo *) sl;
}

/* spacetype; init callback */
static void info_init(struct wmWindowManager *UNUSED(wm), ScrArea *UNUSED(area)) {}

static SpaceLink *info_duplicate(SpaceLink *sl)
{
  SpaceInfo *sinfon = MEM_dupallocN(sl);

  /* clear or remove stuff from old */

  return (SpaceLink *)sinfon;
}

/* add handlers, stuff you only do once or on area/region changes */
static void info_main_region_init(wmWindowManager *wm, ARegion *region)
{
  wmKeyMap *keymap;
  LISTBASE_FOREACH (wmWindow *, window, &wm->windows) {
    if (window->blui_shell_role == WM_BLUI_SHELL_NORMAL) {
      continue;
    }
    const bScreen *screen = WM_window_get_active_screen(window);
    if (!screen) {
      continue;
    }
    LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
      if (BLI_findindex(&area->regionbase, region) >= 0) {
        /* Shell panels are fixed-DPI menus, not an Info report viewport. */
        keymap = WM_keymap_ensure(wm->defaultconf, "View2D", 0, 0);
        WM_event_remove_keymap_handler(&region->handlers, keymap);
        keymap = WM_keymap_ensure(wm->defaultconf, "Frames", 0, 0);
        WM_event_remove_keymap_handler(&region->handlers, keymap);
        if (window->blui_shell_role == WM_BLUI_SHELL_TASKBAR) {
          ED_region_header_init(region);
          keymap = WM_keymap_ensure(wm->defaultconf, "BLUI Taskbar", SPACE_INFO, RGN_TYPE_WINDOW);
          /* Handle taskbar middle clicks before the inherited View2D pan map. */
          WM_event_add_keymap_handler_priority(&region->handlers, keymap, 0);
        }
        else {
          ED_region_panels_init(wm, region);
          region->v2d.keepzoom |= V2D_LOCKZOOM_X | V2D_LOCKZOOM_Y;
          keymap = WM_keymap_ensure(wm->defaultconf, "BLUI Shell Popup", SPACE_INFO, RGN_TYPE_WINDOW);
          WM_event_add_keymap_handler_priority(&region->handlers, keymap, 0);
        }
        return;
      }
    }
  }

  /* force it on init, for old files, until it becomes config */
  region->v2d.scroll = (V2D_SCROLL_RIGHT);

  UI_view2d_region_reinit(&region->v2d, V2D_COMMONVIEW_CUSTOM, region->winx, region->winy);

  /* own keymap */
  keymap = WM_keymap_ensure(wm->defaultconf, "Info", SPACE_INFO, 0);
  WM_event_add_keymap_handler(&region->handlers, keymap);
}

static void info_textview_update_rect(const bContext *C, ARegion *region)
{
  SpaceInfo *sinfo = CTX_wm_space_info(C);
  View2D *v2d = &region->v2d;

  UI_view2d_totRect_set(
      v2d, region->winx - 1, info_textview_height(sinfo, region, CTX_wm_reports(C)));
}

static int info_context(const bContext *C, const char *member, bContextDataResult *result)
{
  const bool taskbar_only = CTX_data_equals(member, "blui_taskbar_button");
  const bool hover = CTX_data_equals(member, "blui_shell_hover_button");
  if (!taskbar_only && !hover && !CTX_data_equals(member, "blui_shell_button")) {
    return CTX_RESULT_MEMBER_NOT_FOUND;
  }
  const wmWindow *window = CTX_wm_window(C);
  const ARegion *region = CTX_wm_region(C);
  if (!window || window->blui_shell_role == WM_BLUI_SHELL_NORMAL ||
      (taskbar_only && window->blui_shell_role != WM_BLUI_SHELL_TASKBAR) || !window->eventstate ||
      !region || region->regiontype != RGN_TYPE_WINDOW)
  {
    return CTX_RESULT_NO_DATA;
  }
  /* Context-menu button_operator is not populated for ordinary region keymaps.
   * Hit-test live UI blocks instead of reusing a previously clicked button. */
  /* eventstate may already contain a later queued mouse move. Use the press
   * being handled, so a quick move after clicking cannot launch another app. */
  const wmEvent *event = hover ? NULL : window->event_queue.first;
  const int *xy = event ? event->xy : window->eventstate->xy;
  const rcti point = {xy[0], xy[0] + 1, xy[1], xy[1] + 1};
  uiBut *button = UI_region_but_find_rect_over(region, &point);
  PointerRNA *properties = button ? UI_but_operator_ptr_get(button) : NULL;
  if (!properties || !properties->data) {
    return CTX_RESULT_NO_DATA;
  }
  CTX_data_pointer_set_ptr(result, properties);
  return CTX_RESULT_OK;
}

static void info_main_region_draw(const bContext *C, ARegion *region)
{
  const wmWindow *window = CTX_wm_window(C);
  if (window && window->blui_shell_role == WM_BLUI_SHELL_TASKBAR) {
    ED_region_header(C, region);
    return;
  }
  if (window && ELEM(window->blui_shell_role, WM_BLUI_SHELL_STARTMENU,
                     WM_BLUI_SHELL_TASK_CHOOSER, WM_BLUI_SHELL_TASK_PREVIEW)) {
    ED_region_panels(C, region);
    return;
  }
  /* draw entirely, view changes should be handled here */
  SpaceInfo *sinfo = CTX_wm_space_info(C);
  View2D *v2d = &region->v2d;

  /* clear and setup matrix */
  UI_ThemeClearColor(TH_BACK);

  /* quick way to avoid drawing if not bug enough */
  if (region->winy < 16) {
    return;
  }

  info_textview_update_rect(C, region);

  /* Works best with no view2d matrix set. */
  UI_view2d_view_ortho(v2d);

  info_textview_main(sinfo, region, CTX_wm_reports(C));

  /* reset view matrix */
  UI_view2d_view_restore(C);

  /* scrollers */
  UI_view2d_scrollers_draw(v2d, NULL);
}

static void info_operatortypes(void)
{
  WM_operatortype_append(FILE_OT_autopack_toggle);
  WM_operatortype_append(FILE_OT_pack_all);
  WM_operatortype_append(FILE_OT_pack_libraries);
  WM_operatortype_append(FILE_OT_unpack_all);
  WM_operatortype_append(FILE_OT_unpack_item);
  WM_operatortype_append(FILE_OT_unpack_libraries);

  WM_operatortype_append(FILE_OT_make_paths_relative);
  WM_operatortype_append(FILE_OT_make_paths_absolute);
  WM_operatortype_append(FILE_OT_report_missing_files);
  WM_operatortype_append(FILE_OT_find_missing_files);
  WM_operatortype_append(INFO_OT_reports_display_update);

  /* info_report.c */
  WM_operatortype_append(INFO_OT_select_pick);
  WM_operatortype_append(INFO_OT_select_all);
  WM_operatortype_append(INFO_OT_select_box);

  WM_operatortype_append(INFO_OT_report_replay);
  WM_operatortype_append(INFO_OT_report_delete);
  WM_operatortype_append(INFO_OT_report_copy);
}

static void info_keymap(struct wmKeyConfig *keyconf)
{
  WM_keymap_ensure(keyconf, "Window", 0, 0);
  WM_keymap_ensure(keyconf, "Info", SPACE_INFO, 0);
}

/* add handlers, stuff you only do once or on area/region changes */
static void info_header_region_init(wmWindowManager *UNUSED(wm), ARegion *region)
{
  ED_region_header_init(region);
}

static void info_header_region_draw(const bContext *C, ARegion *region)
{
  ED_region_header(C, region);
}

static void info_main_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  /* context changes */
  switch (wmn->category) {
    case NC_SPACE:
      if (wmn->data == ND_SPACE_INFO_REPORT) {
        /* redraw also but only for report view, could do less redraws by checking the type */
        ED_region_tag_redraw(region);
      }
      break;
  }
}

static void info_header_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  /* context changes */
  switch (wmn->category) {
    case NC_SCREEN:
      if (ELEM(wmn->data, ND_LAYER, ND_ANIMPLAY)) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_WM:
      if (wmn->data == ND_JOB) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SCENE:
      if (wmn->data == ND_RENDER_RESULT) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SPACE:
      if (wmn->data == ND_SPACE_INFO) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_ID:
      if (wmn->action == NA_RENAME) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

static void info_header_region_message_subscribe(const wmRegionMessageSubscribeParams *params)
{
  struct wmMsgBus *mbus = params->message_bus;
  ARegion *region = params->region;

  wmMsgSubscribeValue msg_sub_value_region_tag_redraw = {NULL};
  msg_sub_value_region_tag_redraw.owner = region;
  msg_sub_value_region_tag_redraw.user_data = region;
  msg_sub_value_region_tag_redraw.notify = ED_region_do_msg_notify_tag_redraw;

  WM_msg_subscribe_rna_anon_prop(mbus, Window, view_layer, &msg_sub_value_region_tag_redraw);
  WM_msg_subscribe_rna_anon_prop(mbus, ViewLayer, name, &msg_sub_value_region_tag_redraw);
}

static void info_space_blend_write(BlendWriter *writer, SpaceLink *sl)
{
  BLO_write_struct(writer, SpaceInfo, sl);
}

void ED_spacetype_info(void)
{
  SpaceType *st = MEM_callocN(sizeof(SpaceType), "spacetype info");
  ARegionType *art;

  st->spaceid = SPACE_INFO;
  STRNCPY(st->name, "Info");

  st->create = info_create;
  st->free = info_free;
  st->init = info_init;
  st->duplicate = info_duplicate;
  st->operatortypes = info_operatortypes;
  st->keymap = info_keymap;
  st->blend_write = info_space_blend_write;
  st->context = info_context;

  /* regions: main window */
  art = MEM_callocN(sizeof(ARegionType), "spacetype info region");
  art->regionid = RGN_TYPE_WINDOW;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_VIEW2D | ED_KEYMAP_FRAMES;

  art->init = info_main_region_init;
  art->draw = info_main_region_draw;
  art->listener = info_main_region_listener;

  BLI_addhead(&st->regiontypes, art);

  /* regions: header */
  art = MEM_callocN(sizeof(ARegionType), "spacetype info region");
  art->regionid = RGN_TYPE_HEADER;
  art->prefsizey = HEADERY;

  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_VIEW2D | ED_KEYMAP_FRAMES | ED_KEYMAP_HEADER;
  art->listener = info_header_listener;
  art->message_subscribe = info_header_region_message_subscribe;
  art->init = info_header_region_init;
  art->draw = info_header_region_draw;

  BLI_addhead(&st->regiontypes, art);

  BKE_spacetype_register(st);
}
