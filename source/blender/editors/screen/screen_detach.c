/* SPDX-License-Identifier: GPL-2.0-or-later */
/** Detach a corner-dragged editor on release outside the source window. */
#include "BKE_context.h"
#include "BKE_report.h"
#include "BLI_listbase.h"
#include "BLI_utildefines.h"
#include "ED_screen.h"
#include "RNA_access.h"
#include "RNA_define.h"
#include "WM_api.h"
#include "wm_window.h"
#include "screen_intern.h"

bool ED_screen_area_detach(bContext *C, ScrArea *area, const int xy[2], ReportList *reports)
{
  wmWindow *source = CTX_wm_window(C);
  wmWindowManager *wm = CTX_wm_manager(C);
  bScreen *source_screen = WM_window_get_active_screen(source);
  if (!area || BLI_findindex(&source_screen->areabase, area) == -1 || ED_area_is_global(area)) {
    return false;
  }
  const int width = MAX2(area->v3->vec.x - area->v1->vec.x, 320);
  const int height = MAX2(area->v3->vec.y - area->v1->vec.y, 240);
  ARegion *region = CTX_wm_region(C);
  wmWindow *destination = WM_window_open(C, "BLUI", xy[0], xy[1] - height, width, height,
                                         area->spacetype, true, false, false, WIN_ALIGN_ABSOLUTE);
  if (!destination) {
    BKE_report(reports, RPT_ERROR, "Failed to detach editor into a new window");
    return false;
  }
  bScreen *destination_screen = WM_window_get_active_screen(destination);
  ScrArea *new_area = destination_screen->areabase.first;
  ED_area_data_copy(new_area, area, true);
  ED_area_tag_redraw(new_area);
  CTX_wm_window_set(C, source);
  CTX_wm_area_set(C, area);
  CTX_wm_region_set(C, region);
  WM_event_modal_handler_region_replace(source, region, NULL);
  if (BLI_listbase_is_single(&source_screen->areabase)) {
    /* Let the active corner modal handler unwind before freeing its window. */
    if (!WM_blui_close_moved_window(C, source, destination)) {
      BKE_report(reports, RPT_WARNING, "Editor opened in a new window; source area could not be closed");
    }
  }
  else if (!screen_area_close(C, source_screen, area)) {
    BKE_report(reports, RPT_WARNING, "Editor opened in a new window; source area could not be closed");
  }
  else {
    CTX_wm_area_set(C, NULL);
    CTX_wm_region_set(C, NULL);
  }
  WM_event_add_notifier(C, NC_SCREEN | NA_EDITED, NULL);
  return true;
}

static int area_detach_exec(bContext *C, wmOperator *op)
{
  int cursor[2];
  RNA_int_get_array(op->ptr, "cursor", cursor);
  return ED_screen_area_detach(C, CTX_wm_area(C), cursor, op->reports) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

void SCREEN_OT_area_detach(wmOperatorType *ot)
{
  ot->name = "Detach Editor to New Window";
  ot->description = "Move the editor into a new window, preserving its current document";
  ot->idname = "SCREEN_OT_area_detach";
  ot->exec = area_detach_exec;
  ot->poll = ED_operator_areaactive;
  RNA_def_int_vector(ot->srna, "cursor", 2, NULL, INT_MIN, INT_MAX, "Cursor", "Drop location", INT_MIN, INT_MAX);
}
