/* SPDX-License-Identifier: GPL-2.0-or-later
 * Derived from Blender 4.5 screen_ops.cc, Copyright Blender Foundation. */
/** Checked layout mutation and document-aware replacement. */
#include "BKE_context.h"
#include "BKE_report.h"
#include "BKE_screen.h"
#include "BLI_listbase.h"
#include "BLI_math.h"
#include "BLI_string.h"
#include "ED_image.h"
#include "ED_screen.h"
#include "RNA_access.h"
#include "RNA_define.h"
#include "WM_api.h"
#include "screen_docking.h"
#include <stdint.h>
#include <stdlib.h>

static const EnumPropertyItem dock_targets[] = {
    {SCREEN_DOCK_CENTER, "CENTER", 0, "Center", "Replace this area"},
    {SCREEN_DOCK_LEFT, "LEFT", 0, "Left", "Move area to the left"},
    {SCREEN_DOCK_RIGHT, "RIGHT", 0, "Right", "Move area to the right"},
    {SCREEN_DOCK_TOP, "TOP", 0, "Top", "Move area to the top"},
    {SCREEN_DOCK_BOTTOM, "BOTTOM", 0, "Bottom", "Move area to the bottom"},
    {SCREEN_DOCK_JOIN, "JOIN", 0, "Join", "Join adjacent areas"},
    {0, NULL, 0, NULL, NULL}};

static void restore_context(bContext *C, wmWindow *window, ScrArea *area, ARegion *region)
{
  CTX_wm_window_set(C, window);
  const bool live = area &&
                    BLI_findindex(&WM_window_get_active_screen(window)->areabase, area) != -1;
  CTX_wm_area_set(C, live ? area : NULL);
  CTX_wm_region_set(
      C, live && region && BLI_findindex(&area->regionbase, region) != -1 ? region : NULL);
}

bool screen_dock_apply(bContext *C,
                       wmWindow *source_window,
                       ScrArea *source,
                       wmWindow *target_window,
                       ScrArea *target,
                       ScreenDockTarget dock,
                       float factor,
                       bool confirmed,
                       ReportList *reports)
{
  wmWindowManager *manager = CTX_wm_manager(C);
  if (!source_window || !target_window || !source || !target || source == target ||
      BLI_findindex(&manager->windows, source_window) == -1 ||
      BLI_findindex(&manager->windows, target_window) == -1)
  {
    BKE_report(reports, RPT_ERROR, "Docking cancelled: source or target editor changed");
    return false;
  }
  bScreen *source_screen = WM_window_get_active_screen(source_window);
  bScreen *target_screen = WM_window_get_active_screen(target_window);
  if (source_screen->temp || target_screen->temp ||
      BLI_findindex(&source_screen->areabase, source) == -1 ||
      BLI_findindex(&target_screen->areabase, target) == -1 || ED_area_is_global(source) ||
      ED_area_is_global(target))
  {
    BKE_report(reports, RPT_ERROR, "Docking cancelled: source or target editor changed");
    return false;
  }
  wmWindow *previous_window = CTX_wm_window(C);
  ScrArea *previous_area = CTX_wm_area(C);
  ARegion *previous_region = CTX_wm_region(C);
  if (!confirmed && ELEM(dock, SCREEN_DOCK_CENTER, SCREEN_DOCK_JOIN)) {
    char arguments[1024];
    BLI_snprintf(arguments,
                 sizeof(arguments),
                 "{\"source_window\":\"%llu\",\"source_area\":\"%llu\",\"source_space\":\"%llu\","
                 "\"target_window\":\"%llu\",\"target_area\":\"%llu\",\"dock_target\":\"%s\","
                 "\"factor\":%.9g}",
                 (unsigned long long)(uintptr_t)source_window,
                 (unsigned long long)(uintptr_t)source,
                 (unsigned long long)(uintptr_t)source->spacedata.first,
                 (unsigned long long)(uintptr_t)target_window,
                 (unsigned long long)(uintptr_t)target,
                 dock == SCREEN_DOCK_JOIN ? "JOIN" : "CENTER",
                 factor);
    CTX_wm_window_set(C, target_window);
    CTX_wm_area_set(C, target);
    CTX_wm_region_set(C, NULL);
    bool deferred = WM_blui_document_confirm_dock(C, arguments);
    restore_context(C, previous_window, previous_area, previous_region);
    if (deferred) {
      return true;
    }
  }
  CTX_wm_window_set(C, source_window);
  CTX_wm_area_set(C, source);
  CTX_wm_region_set(C, NULL);
  if (dock == SCREEN_DOCK_JOIN) {
    bool joined = source_window == target_window &&
                  screen_area_join(C, source_screen, source, target);
    if (joined) {
      ED_image_document_collect(CTX_data_main(C));
      ED_area_tag_redraw(source);
      WM_event_add_notifier(C, NC_SCREEN | NA_EDITED, NULL);
    }
    restore_context(C, previous_window, previous_area, previous_region);
    return joined;
  }
  if (dock != SCREEN_DOCK_CENTER) {
    const eScreenAxis axis = ELEM(dock, SCREEN_DOCK_LEFT, SCREEN_DOCK_RIGHT) ? SCREEN_AXIS_V :
                                                                               SCREEN_AXIS_H;
    const float split = ELEM(dock, SCREEN_DOCK_RIGHT, SCREEN_DOCK_TOP) ? 1.0f - factor : factor;
    ScrArea *created = area_split(target_window, target_screen, target, axis, split, true);
    if (!created) {
      restore_context(C, previous_window, previous_area, previous_region);
      BKE_report(reports, RPT_ERROR, "Target editor is too small to split");
      return false;
    }
    if (factor <= 0.5f) {
      target = created;
    }
    else {
      ED_area_tag_redraw(created);
    }
  }
  /* Swap actual editor data, preserving console history and unsaved buffers. */
  WM_event_modal_handler_region_replace(source_window, previous_region, NULL);
  ED_area_exit(C, source);
  CTX_wm_window_set(C, target_window);
  CTX_wm_area_set(C, target);
  CTX_wm_region_set(C, NULL);
  ED_area_exit(C, target);
  ED_area_data_swap(target, source);
  source_screen->active_region = target_screen->active_region = NULL;
  ED_area_init(manager, target_window, target);
  ED_area_tag_redraw(target);
  CTX_wm_window_set(C, source_window);
  CTX_wm_area_set(C, source);
  CTX_wm_region_set(C, NULL);
  ED_area_init(manager, source_window, source);
  if (source_window != target_window && BLI_listbase_is_single(&source_screen->areabase)) {
    if (!WM_blui_close_moved_window(C, source_window, target_window)) {
      BKE_report(reports, RPT_WARNING, "Editor moved; source window could not be closed");
    }
  }
  else if (!screen_area_close(C, source_screen, source)) {
    ED_area_tag_redraw(source);
    BKE_report(reports, RPT_WARNING, "Editor moved; source area could not be closed");
  }
  ED_image_document_collect(CTX_data_main(C));
  WM_event_add_notifier(C, NC_SCREEN | NA_EDITED, NULL);
  WM_event_add_notifier(C, NC_WINDOW, NULL);
  restore_context(C, previous_window, previous_area, previous_region);
  return true;
}

static uintptr_t pointer_property(wmOperator *op, const char *name)
{
  char value[32], *end;
  RNA_string_get(op->ptr, name, value);
  unsigned long long pointer = strtoull(value, &end, 10);
  return *end == '\0' ? (uintptr_t)pointer : 0;
}

static int area_dock_exec(bContext *C, wmOperator *op)
{
  wmWindow *source_window = NULL, *target_window = NULL;
  ScrArea *source = NULL, *target = NULL;
  const uintptr_t source_win = pointer_property(op, "source_window"),
                  target_win = pointer_property(op, "target_window");
  const uintptr_t source_ptr = pointer_property(op, "source_area"),
                  target_ptr = pointer_property(op, "target_area");
  const uintptr_t source_space = pointer_property(op, "source_space");
  LISTBASE_FOREACH (wmWindow *, window, &CTX_wm_manager(C)->windows) {
    if ((uintptr_t)window == source_win) {
      source_window = window;
    }
    if ((uintptr_t)window == target_win) {
      target_window = window;
    }
    if ((uintptr_t)window != source_win && (uintptr_t)window != target_win) {
      continue;
    }
    LISTBASE_FOREACH (ScrArea *, area, &WM_window_get_active_screen(window)->areabase) {
      if ((uintptr_t)window == source_win && (uintptr_t)area == source_ptr) {
        source = area;
      }
      if ((uintptr_t)window == target_win && (uintptr_t)area == target_ptr) {
        target = area;
      }
    }
  }
  if (!source || (source_space && (uintptr_t)source->spacedata.first != source_space)) {
    BKE_report(op->reports, RPT_ERROR, "Docking cancelled: source or target editor changed");
    return OPERATOR_CANCELLED;
  }
  return screen_dock_apply(C,
                           source_window,
                           source,
                           target_window,
                           target,
                           RNA_enum_get(op->ptr, "dock_target"),
                           RNA_float_get(op->ptr, "factor"),
                           RNA_boolean_get(op->ptr, "confirmed"),
                           op->reports) ?
             OPERATOR_FINISHED :
             OPERATOR_CANCELLED;
}

void SCREEN_OT_area_dock(wmOperatorType *ot)
{
  ot->name = "Dock Editor";
  ot->description = "Move an editor between areas or windows, preserving its current document";
  ot->idname = "SCREEN_OT_area_dock";
  ot->exec = area_dock_exec;
  ot->poll = ED_operator_screenactive;
  ot->flag = OPTYPE_INTERNAL;
  const char *names[] = {
      "source_window", "source_area", "source_space", "target_window", "target_area"};
  for (int i = 0; i < 5; i++) {
    PropertyRNA *prop = RNA_def_string(
        ot->srna, names[i], NULL, 32, "Editor", "Live editor identity");
    RNA_def_property_flag(prop, PROP_HIDDEN | PROP_SKIP_SAVE);
  }
  RNA_def_enum(
      ot->srna, "dock_target", dock_targets, SCREEN_DOCK_CENTER, "Location", "Docking target");
  RNA_def_float(
      ot->srna, "factor", 0.5f, 0.01f, 0.99f, "Factor", "Docked area proportion", 0.01f, 0.99f);
  PropertyRNA *prop = RNA_def_boolean(
      ot->srna, "confirmed", false, "Confirmed", "Continue after document confirmation");
  RNA_def_property_flag(prop, PROP_HIDDEN | PROP_SKIP_SAVE);
}
