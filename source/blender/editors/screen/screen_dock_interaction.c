/* SPDX-License-Identifier: GPL-2.0-or-later
 * Derived from Blender 4.5 screen_ops.cc, Copyright Blender Foundation. */
/** Unified corner drag: split, join, move, dock, replace, or detach on release. */
#include "BKE_context.h"
#include "BKE_global.h"
#include "BKE_screen.h"
#include "BLI_listbase.h"
#include "BLI_math.h"
#include "BLT_translation.h"
#include "ED_screen.h"
#include "ED_screen_types.h"
#include "MEM_guardedalloc.h"
#include "RNA_access.h"
#include "RNA_define.h"
#include "WM_api.h"
#include "WM_types.h"
#include "screen_docking.h"

static bool live_area(wmWindowManager *manager, wmWindow *window, const ScrArea *area)
{
  return window && area && BLI_findindex(&manager->windows, window) != -1 &&
         BLI_findindex(&WM_window_get_active_screen(window)->areabase, area) != -1;
}

static void source_draw(const wmWindow *window, void *userdata)
{
  const wmOperator *op = userdata;
  ScreenDockState *state = op->customdata;
  if (state && BLI_findindex(&WM_window_get_active_screen(window)->areabase, state->source) != -1)
  {
    screen_dock_draw(window, state, false);
  }
}

static void target_draw(const wmWindow *window, void *userdata)
{
  const wmOperator *op = userdata;
  ScreenDockState *state = op->customdata;
  if (state && BLI_findindex(&WM_window_get_active_screen(window)->areabase, state->target) != -1)
  {
    screen_dock_draw(window, state, true);
  }
}

static void draw_window_update(bContext *C, wmOperator *op)
{
  ScreenDockState *state = op->customdata;
  if (state->draw_window == state->target_window) {
    return;
  }
  if (state->target_draw && BLI_findindex(&CTX_wm_manager(C)->windows, state->draw_window) != -1) {
    WM_draw_cb_exit(state->draw_window, state->target_draw);
    LISTBASE_FOREACH (ScrArea *, area, &WM_window_get_active_screen(state->draw_window)->areabase)
    {
      ED_area_tag_redraw(area);
    }
  }
  state->target_draw = NULL;
  state->draw_window = state->target_window;
  if (state->draw_window) {
    state->target_draw = WM_draw_cb_activate(state->draw_window, target_draw, op);
  }
}

static void finish(bContext *C, wmOperator *op)
{
  ScreenDockState *state = op->customdata;
  if (!state) {
    return;
  }
  wmWindowManager *manager = CTX_wm_manager(C);
  if (BLI_findindex(&manager->windows, state->source_window) != -1) {
    if (state->source_draw) {
      WM_draw_cb_exit(state->source_window, state->source_draw);
    }
    WM_cursor_set(state->source_window, WM_CURSOR_DEFAULT);
    bScreen *screen = WM_window_get_active_screen(state->source_window);
    BKE_screen_remove_double_scredges(screen);
    BKE_screen_remove_unused_scredges(screen);
    BKE_screen_remove_unused_scrverts(screen);
  }
  if (state->target_draw && BLI_findindex(&manager->windows, state->draw_window) != -1) {
    WM_draw_cb_exit(state->draw_window, state->target_draw);
  }
  if (live_area(manager, state->source_window, state->source)) {
    ED_area_tag_redraw(state->source);
  }
  if (live_area(manager, state->target_window, state->target)) {
    ED_area_tag_redraw(state->target);
  }
  MEM_freeN(state);
  op->customdata = NULL;
  ED_workspace_status_text(C, NULL);
  G.moving &= ~G_TRANSFORM_WM;
}

static bool editable(bContext *C)
{
  bScreen *screen = CTX_wm_screen(C);
  return screen && !screen->temp && screen->state == SCREENNORMAL;
}

static bool initialize(bContext *C, wmOperator *op, ScrArea *source, ScrArea *target)
{
  if (!source) {
    int xy[2];
    PropertyRNA *prop = RNA_struct_find_property(op->ptr, "source_xy");
    if (RNA_property_is_set(op->ptr, prop)) {
      RNA_property_int_get_array(op->ptr, prop, xy);
      source = BKE_screen_find_area_xy(CTX_wm_screen(C), SPACE_TYPE_ANY, xy);
    }
    prop = RNA_struct_find_property(op->ptr, "target_xy");
    if (RNA_property_is_set(op->ptr, prop)) {
      RNA_property_int_get_array(op->ptr, prop, xy);
      target = BKE_screen_find_area_xy(CTX_wm_screen(C), SPACE_TYPE_ANY, xy);
    }
    if (!source) {
      prop = RNA_struct_find_property(op->ptr, "cursor");
      if (RNA_property_is_set(op->ptr, prop)) {
        RNA_property_int_get_array(op->ptr, prop, xy);
        screen_area_edge_from_cursor(C, xy, &source, &target);
      }
    }
    if (!source) {
      source = CTX_wm_area(C);
    }
  }
  if (!source || ED_area_is_global(source)) {
    return false;
  }
  ScreenDockState *state = MEM_callocN(sizeof(ScreenDockState), "4.5 area docking");
  state->source = source;
  state->target = target;
  state->source_window = WM_window_find_by_area(CTX_wm_manager(C), source);
  state->target_window = WM_window_find_by_area(CTX_wm_manager(C), target);
  state->join_direction = SCREEN_DIR_NONE;
  state->factor = 0.5f;
  if (!state->source_window) {
    MEM_freeN(state);
    return false;
  }
  op->customdata = state;
  return true;
}

static int join_exec(bContext *C, wmOperator *op)
{
  if (!initialize(C, op, NULL, NULL)) {
    return OPERATOR_CANCELLED;
  }
  ScreenDockState *state = op->customdata;
  bool ok = state->target && state->target_window == state->source_window &&
            area_getorientation(state->source, state->target) != SCREEN_DIR_NONE &&
            screen_dock_apply(C,
                              state->source_window,
                              state->source,
                              state->target_window,
                              state->target,
                              SCREEN_DOCK_JOIN,
                              0.5f,
                              false,
                              op->reports);
  finish(C, op);
  return ok ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static int join_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  if (event->type == EVT_ACTIONZONE_AREA) {
    const sActionzoneData *zone = event->customdata;
    if (!zone || zone->modifier > 0 || !zone->sa1) {
      return OPERATOR_PASS_THROUGH;
    }
    if (!initialize(C, op, zone->sa1, zone->sa2)) {
      return OPERATOR_CANCELLED;
    }
    ScreenDockState *state = op->customdata;
    state->start[0] = zone->x;
    state->start[1] = zone->y;
  }
  else {
    if (!initialize(C, op, NULL, NULL)) {
      return OPERATOR_CANCELLED;
    }
    ScreenDockState *state = op->customdata;
    state->start[0] = state->source->totrct.xmin;
    state->start[1] = state->source->totrct.ymax;
  }
  ScreenDockState *state = op->customdata;
  state->source_draw = WM_draw_cb_activate(state->source_window, source_draw, op);
  screen_dock_update(C, state, event);
  draw_window_update(C, op);
  WM_cursor_set(state->source_window, screen_dock_cursor(state, event));
  ED_area_tag_redraw(state->source);
  if (state->target) {
    ED_area_tag_redraw(state->target);
  }
  WM_event_add_notifier(C, NC_WINDOW, NULL);
  G.moving |= G_TRANSFORM_WM;
  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

static void join_cancel(bContext *C, wmOperator *op)
{
  finish(C, op);
  WM_event_add_notifier(C, NC_WINDOW, NULL);
}

static int join_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  ScreenDockState *state = op->customdata;
  if (!state || !live_area(CTX_wm_manager(C), state->source_window, state->source)) {
    join_cancel(C, op);
    return OPERATOR_CANCELLED;
  }
  if (ELEM(event->type, RIGHTMOUSE, EVT_ESCKEY, WINDEACTIVATE)) {
    join_cancel(C, op);
    return OPERATOR_CANCELLED;
  }
  if (event->type == MOUSEMOVE || event->type == LEFTMOUSE) {
    screen_dock_update(C, state, event);
    draw_window_update(C, op);
    WM_cursor_set(state->source_window, screen_dock_cursor(state, event));
    const char *hint = state->source == state->target ?
                           IFACE_("LMB: Split  |  Esc: Cancel  |  Ctrl: Snap") :
                           IFACE_("LMB: Dock  |  Esc: Cancel  |  Ctrl: Snap  |  Alt: Precision");
    ED_workspace_status_text(C, hint);
    WM_event_add_notifier(C, NC_WINDOW, NULL);
  }
  if (event->type != LEFTMOUSE || event->val != KM_RELEASE) {
    return OPERATOR_RUNNING_MODAL;
  }
  bool ok = false;
  if (!state->target) {
    if (event->xy[0] < 0 || event->xy[1] < 0 ||
        event->xy[0] > WM_window_pixels_x(state->source_window) ||
        event->xy[1] > WM_window_pixels_y(state->source_window))
    {
      ScrArea *source = state->source;
      finish(C, op);
      return ED_screen_area_detach(C, source, event->xy, op->reports) ? OPERATOR_FINISHED :
                                                                        OPERATOR_CANCELLED;
    }
  }
  else if (state->source == state->target) {
    if (state->split_factor > 0.0001f) {
      ScrArea *created = area_split(state->source_window,
                                    WM_window_get_active_screen(state->source_window),
                                    state->source,
                                    state->split_direction,
                                    state->split_factor,
                                    true);
      if (created) {
        const bool large_v = state->split_direction == SCREEN_AXIS_V &&
                             ((state->start[0] < event->xy[0] && state->split_factor > 0.5f) ||
                              (state->start[0] > event->xy[0] && state->split_factor < 0.5f));
        const bool large_h = state->split_direction == SCREEN_AXIS_H &&
                             ((state->start[1] < event->xy[1] && state->split_factor > 0.5f) ||
                              (state->start[1] > event->xy[1] && state->split_factor < 0.5f));
        if (large_v || large_h) {
          SWAP(ScrVert *, state->source->v1, created->v1);
          SWAP(ScrVert *, state->source->v2, created->v2);
          SWAP(ScrVert *, state->source->v3, created->v3);
          SWAP(ScrVert *, state->source->v4, created->v4);
          SWAP(rcti, state->source->totrct, created->totrct);
          SWAP(short, state->source->winx, created->winx);
          SWAP(short, state->source->winy, created->winy);
        }
        ED_area_tag_redraw(created);
        ED_area_tag_redraw(state->source);
        ok = true;
      }
    }
  }
  else if (state->dock_target != SCREEN_DOCK_NONE || state->join_direction != SCREEN_DIR_NONE) {
    ok = screen_dock_apply(C,
                           state->source_window,
                           state->source,
                           state->target_window,
                           state->target,
                           state->dock_target == SCREEN_DOCK_NONE ? SCREEN_DOCK_JOIN :
                                                                    state->dock_target,
                           state->factor,
                           false,
                           op->reports);
  }
  finish(C, op);
  WM_event_add_notifier(C, NC_SCREEN | NA_EDITED, NULL);
  return ok ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

void SCREEN_OT_area_join45(wmOperatorType *ot)
{
  ot->name = "Join Area";
  ot->description = "Split, join or dock editors within or between windows";
  ot->idname = "SCREEN_OT_area_join";
  ot->exec = join_exec;
  ot->invoke = join_invoke;
  ot->modal = join_modal;
  ot->cancel = join_cancel;
  ot->poll = editable;
  ot->flag = OPTYPE_BLOCKING;
  RNA_def_int_vector(
      ot->srna, "source_xy", 2, NULL, INT_MIN, INT_MAX, "Source location", "", INT_MIN, INT_MAX);
  RNA_def_int_vector(
      ot->srna, "target_xy", 2, NULL, INT_MIN, INT_MAX, "Target location", "", INT_MIN, INT_MAX);
  PropertyRNA *prop = RNA_def_int_vector(ot->srna,
                                         "cursor",
                                         2,
                                         NULL,
                                         INT_MIN,
                                         INT_MAX,
                                         "Cursor",
                                         "Legacy edge menu location",
                                         INT_MIN,
                                         INT_MAX);
  RNA_def_property_flag(prop, PROP_HIDDEN | PROP_SKIP_SAVE);
}
