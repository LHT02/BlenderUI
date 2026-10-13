/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "screen_intern.h"

typedef enum ScreenDockTarget {
  SCREEN_DOCK_NONE = 0,
  SCREEN_DOCK_CENTER,
  SCREEN_DOCK_LEFT,
  SCREEN_DOCK_RIGHT,
  SCREEN_DOCK_TOP,
  SCREEN_DOCK_BOTTOM,
  SCREEN_DOCK_JOIN,
} ScreenDockTarget;

typedef struct ScreenDockState {
  ScrArea *source, *target;
  wmWindowManager *manager;
  bScreen *source_screen;
  SpaceLink *source_space;
  wmWindow *source_window, *target_window, *draw_window;
  eScreenDir join_direction;
  eScreenAxis split_direction;
  ScreenDockTarget dock_target;
  float factor, split_factor;
  int start[2], current[2];
  void *source_draw, *target_draw;
} ScreenDockState;

void screen_dock_update(struct bContext *C, ScreenDockState *state, const struct wmEvent *event);
int screen_dock_cursor(const ScreenDockState *state, const struct wmEvent *event);
bool screen_dock_apply(struct bContext *C,
                       wmWindow *source_window,
                       ScrArea *source,
                       wmWindow *target_window,
                       ScrArea *target,
                       ScreenDockTarget dock,
                       float factor,
                       bool confirmed,
                       struct ReportList *reports);
void screen_dock_draw(const wmWindow *window, const ScreenDockState *state, bool destination);
void SCREEN_OT_area_join45(struct wmOperatorType *ot);
void SCREEN_OT_area_dock(struct wmOperatorType *ot);
