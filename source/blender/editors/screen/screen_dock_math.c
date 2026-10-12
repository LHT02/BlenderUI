/* SPDX-License-Identifier: GPL-2.0-or-later
 * Derived from Blender 4.5 screen_ops.cc, Copyright Blender Foundation. */
/** Split/join/docking classification and modifier snapping, without layout mutation. */
#include "BKE_context.h"
#include "BKE_global.h"
#include "BKE_screen.h"
#include "BLI_listbase.h"
#include "BLI_math.h"
#include "BLI_rect.h"
#include "ED_screen.h"
#include "UI_interface.h"
#include "WM_api.h"
#include "WM_types.h"
#include "screen_docking.h"
#include <limits.h>
#include <stdlib.h>

static float docking_snap(float position, const wmEvent *event)
{
  const bool alt = event->modifier & KM_ALT, ctrl = event->modifier & KM_CTRL;
  float factor = position * ((alt || ctrl) ? 2.5f : 2.0f);
  if (!alt && factor >= 0.4375f && factor < 0.5625f) {
    factor = factor < 0.5f ? 0.499999f : 0.500001f;
  }
  if (ctrl) {
    if (factor < 0.1875f) {
      factor = 0.125f;
    }
    else if (factor < 0.3125f) {
      factor = 0.25f;
    }
    else if (factor < 0.4375f) {
      factor = 0.375f;
    }
    else if (factor >= 0.5625f && factor < 0.6875f) {
      factor = 0.625f;
    }
    else if (factor >= 0.6875f && factor < 0.8125f) {
      factor = 0.75f;
    }
    else if (factor > 0.8125f) {
      factor = 0.875f;
    }
  }
  return clamp_f(factor, 0.01f, 0.99f);
}

static float split_factor(const ScreenDockState *state, const wmEvent *event)
{
  const ScrArea *area = state->source;
  const int axis = state->split_direction == SCREEN_AXIS_V ? 0 : 1;
  const int origin = axis ? area->totrct.ymin : area->totrct.xmin;
  const int size = axis ? area->winy + 1 : area->winx + 1;
  float factor = (float)(event->xy[axis] - origin) / MAX2(size, 1);
  if (event->modifier & KM_CTRL) {
    int distance = INT_MAX, location = 0;
    LISTBASE_FOREACH (
        const ScrVert *, vertex, &WM_window_get_active_screen(state->source_window)->vertbase)
    {
      const int value = (&vertex->vec.x)[axis];
      if (abs(value - event->xy[axis]) < distance) {
        distance = abs(value - event->xy[axis]);
        location = value;
      }
    }
    const float neighbor = (float)(location - origin) / MAX2(size, 1);
    const float fraction = roundf(factor * 12.0f) / 12.0f;
    factor = fabsf(neighbor - factor) < fabsf(fraction - factor) ? neighbor : fraction;
  }
  else if (factor >= 0.48f && factor < 0.52f) {
    factor = factor < 0.5f ? 0.499999f : 0.500001f;
  }
  const float minimum = (2.0f * ED_area_headersize()) / MAX2(size, 1);
  return minimum < 0.5f ? clamp_f(factor, minimum, 1.0f - minimum) : 0.5f;
}

static ScreenDockTarget docking_target(ScreenDockState *state, const wmEvent *event)
{
  ScrArea *area = state->target;
  const int x = state->current[0] - area->totrct.xmin;
  const int y = state->current[1] - area->totrct.ymin;
  const float fx = (float)x / MAX2(area->winx, 1), fy = (float)y / MAX2(area->winy, 1);
  const int min_x = 2 * AREAMINX * UI_SCALE_FAC, min_y = 2 * HEADERY * UI_SCALE_FAC;
  if (state->source_window == state->target_window) {
    if (SCREEN_DIR_IS_VERTICAL(state->join_direction) &&
        event->xy[0] >= state->source->totrct.xmin && event->xy[0] <= state->source->totrct.xmax)
    {
      const int threshold = MIN2(area->winy * 0.25f, 5 * HEADERY * UI_SCALE_FAC);
      if (area->winy < min_y || (state->join_direction == SCREEN_DIR_N && y < threshold) ||
          (state->join_direction == SCREEN_DIR_S && area->winy - y < threshold))
      {
        return SCREEN_DOCK_NONE;
      }
    }
    if (SCREEN_DIR_IS_HORIZONTAL(state->join_direction) &&
        event->xy[1] >= state->source->totrct.ymin && event->xy[1] <= state->source->totrct.ymax)
    {
      const int threshold = MIN2(area->winx * 0.25f, 5 * AREAMINX * UI_SCALE_FAC);
      if (area->winx < min_x ||
          (state->join_direction == SCREEN_DIR_W && area->winx - x < threshold) ||
          (state->join_direction == SCREEN_DIR_E && x < threshold))
      {
        return SCREEN_DOCK_NONE;
      }
    }
  }
  state->join_direction = SCREEN_DIR_NONE;
  state->factor = 0.5f;
  const float min_fx = 1.5f * AREAMINX * UI_SCALE_FAC / MAX2(area->winx, 1);
  const float min_fy = 1.5f * HEADERY * UI_SCALE_FAC / MAX2(area->winy, 1);
  if (area->winx < min_x * 3) {
    if (fy > 0.4f && fy < 0.6f) {
      return SCREEN_DOCK_CENTER;
    }
    state->factor = docking_snap(MAX2(y > area->winy / 2 ? 1.0f - fy : fy, min_fy), event);
    return y > area->winy / 2 ? SCREEN_DOCK_TOP : SCREEN_DOCK_BOTTOM;
  }
  if (area->winy < min_y * 3) {
    if (fx > 0.4f && fx < 0.6f) {
      return SCREEN_DOCK_CENTER;
    }
    state->factor = docking_snap(MAX2(x > area->winx / 2 ? 1.0f - fx : fx, min_fx), event);
    return x > area->winx / 2 ? SCREEN_DOCK_RIGHT : SCREEN_DOCK_LEFT;
  }
  if (fx > 0.4f && fx < 0.6f && fy > 0.4f && fy < 0.6f) {
    return SCREEN_DOCK_CENTER;
  }
  const float ratio = (float)area->winx / MAX2(area->winy, 1);
  const bool upper_left = (float)x / (y + 1) < ratio;
  const bool lower_left = (float)x / (area->winy - y + 1) < ratio;
  if (upper_left && !lower_left) {
    state->factor = docking_snap(MAX2(1.0f - fy, min_fy), event);
    return SCREEN_DOCK_TOP;
  }
  if (!upper_left && lower_left) {
    state->factor = docking_snap(MAX2(fy, min_fy), event);
    return SCREEN_DOCK_BOTTOM;
  }
  state->factor = docking_snap(MAX2(upper_left ? fx : 1.0f - fx, min_fx), event);
  return upper_left ? SCREEN_DOCK_LEFT : SCREEN_DOCK_RIGHT;
}

void screen_dock_update(bContext *C, ScreenDockState *state, const wmEvent *event)
{
  (void)C;
  state->target_window = WM_window_find_under_cursor(
      state->source_window, event->xy, state->current);
  state->target = state->target_window ?
                      BKE_screen_find_area_xy(WM_window_get_active_screen(state->target_window),
                                              SPACE_TYPE_ANY,
                                              state->current) :
                      NULL;
  if (!state->target_window || !state->target || ED_area_is_global(state->target) ||
      WM_window_get_active_screen(state->target_window)->temp)
  {
    state->target = NULL;
  }
  state->join_direction = SCREEN_DIR_NONE;
  state->dock_target = SCREEN_DOCK_NONE;
  if (!state->target) {
    return;
  }
  if (state->source == state->target) {
    const int threshold = 30 * UI_SCALE_FAC;
    if (MAX2(abs(state->start[0] - event->xy[0]), abs(state->start[1] - event->xy[1])) <=
        threshold)
    {
      state->split_factor = 0.0f;
      return;
    }
    state->split_direction = abs(state->start[0] - event->xy[0]) >
                                     abs(state->start[1] - event->xy[1]) ?
                                 SCREEN_AXIS_V :
                                 SCREEN_AXIS_H;
    state->split_factor = split_factor(state, event);
    return;
  }
  if (state->source_window == state->target_window) {
    state->join_direction = area_getorientation(state->source, state->target);
  }
  state->dock_target = docking_target(state, event);
}

int screen_dock_cursor(const ScreenDockState *state, const wmEvent *event)
{
  if (!state->target) {
    return event->xy[0] < 0 || event->xy[1] < 0 ||
                   event->xy[0] > WM_window_pixels_x(state->source_window) ||
                   event->xy[1] > WM_window_pixels_y(state->source_window) ?
               WM_CURSOR_EDIT :
               WM_CURSOR_STOP;
  }
  if (state->source == state->target) {
    return state->split_factor > 0.0001f ?
               (state->split_direction == SCREEN_AXIS_V ? WM_CURSOR_V_SPLIT : WM_CURSOR_H_SPLIT) :
               WM_CURSOR_EDIT;
  }
  switch (state->join_direction) {
    case SCREEN_DIR_N:
      return WM_CURSOR_N_ARROW;
    case SCREEN_DIR_S:
      return WM_CURSOR_S_ARROW;
    case SCREEN_DIR_W:
      return WM_CURSOR_W_ARROW;
    case SCREEN_DIR_E:
      return WM_CURSOR_E_ARROW;
    default:
      return state->dock_target == SCREEN_DOCK_NONE ? WM_CURSOR_STOP : WM_CURSOR_HAND;
  }
}
