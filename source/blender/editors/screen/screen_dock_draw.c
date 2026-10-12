/* SPDX-License-Identifier: GPL-2.0-or-later
 * Derived from Blender 4.5 screen_draw.cc, Copyright Blender Foundation. */
/** Rounded split/dock previews and editor-labelled drag hints. */
#include "BKE_global.h"
#include "BLF_api.h"
#include "BLI_math.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLT_translation.h"
#include "DNA_userdef_types.h"
#include "GPU_immediate.h"
#include "GPU_state.h"
#include "RNA_access.h"
#include "RNA_enum_types.h"
#include "UI_interface.h"
#include "UI_interface_icons.h"
#include "UI_resources.h"
#include "WM_api.h"
#include "screen_docking.h"

static float editor_radius(void)
{
  return 7.0f * U.pixelsize;
}

static void frame(const rctf *rect)
{
  const float outline[4] = {1.0f, 1.0f, 1.0f, 0.4f};
  const float inner[4] = {1.0f, 1.0f, 1.0f, 0.10f};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv_ex(rect, inner, NULL, 1.0f, outline, U.pixelsize, editor_radius());
}

static void darken(const ScrArea *area)
{
  rctf rect;
  BLI_rctf_rcti_copy(&rect, &area->totrct);
  const float color[4] = {0.0f, 0.0f, 0.0f, 0.7f};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv_ex(&rect, color, NULL, 1.0f, NULL, U.pixelsize, editor_radius());
}

static void drag_tip(const wmWindow *window, const ScrArea *area, int x, int y, const char *hint)
{
  const int item_index = RNA_enum_from_value(rna_enum_space_type_items, area->spacetype);
  const char *name = item_index >= 0 ? IFACE_(rna_enum_space_type_items[item_index].name) :
                                       IFACE_("Editor");
  const int icon = item_index >= 0 ? rna_enum_space_type_items[item_index].icon : ICON_NONE;
  const uiFontStyle *font = UI_FSTYLE_WIDGET;
  const uiWidgetColors *colors = &UI_GetTheme()->tui.wcol_tooltip;
  UI_fontstyle_set(font);
  const float scale = UI_SCALE_FAC;
  const float margin = 4.0f * scale, icon_width = 16.0f * scale, gap = 5.0f * scale;
  const int line_height = BLF_height_max(font->uifont_id);
  const float width = 2 * margin +
                      MAX2(BLF_width(font->uifont_id, hint, strlen(hint)),
                           BLF_width(font->uifont_id, name, strlen(name)) + icon_width + gap);
  const float height = 2 * margin + 2 * line_height + gap;
  const int left = MAX2(0, MIN2(x + 5 * scale, WM_window_pixels_x(window) - width));
  const int top = MAX2(y - 7 * scale, height);
  rctf rect = {left, left + width, top - height, top};
  float background[4];
  rgba_uchar_to_float(background, colors->inner);
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&rect, true, colors->roundness * U.widget_unit, background);
  UI_icon_draw_ex(left + margin,
                  top - height + margin,
                  icon,
                  1.0f / scale,
                  1.0f,
                  0.0f,
                  colors->text,
                  true,
                  NULL);
  UI_fontstyle_draw_simple(font, left + margin, top - margin - line_height, hint, colors->text);
  UI_fontstyle_draw_simple(font,
                           left + margin + icon_width + gap,
                           top - height + margin - BLF_descender(font->uifont_id),
                           name,
                           colors->text);
}

void screen_draw_split_preview(ScrArea *area, const eScreenAxis axis, const float factor)
{
  rctf first;
  BLI_rctf_rcti_copy(&first, &area->totrct);
  GPU_blend(GPU_BLEND_ALPHA);
  if (factor < 0.0001f || factor > 0.9999f) {
    frame(&first);
    GPU_blend(GPU_BLEND_NONE);
    return;
  }
  rctf second = first;
  const float point = axis == SCREEN_AXIS_V ? interpf(first.xmax, first.xmin, factor) :
                                              interpf(first.ymax, first.ymin, factor);
  if (axis == SCREEN_AXIS_V) {
    first.xmax = point - U.pixelsize;
    second.xmin = point + U.pixelsize;
  }
  else {
    first.ymax = point - U.pixelsize;
    second.ymin = point + U.pixelsize;
  }
  frame(&first);
  frame(&second);
  GPU_blend(GPU_BLEND_NONE);
}

void screen_dock_draw(const wmWindow *window, const ScreenDockState *state, const bool destination)
{
  GPU_blend(GPU_BLEND_ALPHA);
  if (!destination) {
    if (state->source == state->target) {
      screen_draw_split_preview(state->source, state->split_direction, state->split_factor);
      GPU_blend(GPU_BLEND_ALPHA);
      drag_tip(window,
               state->source,
               window->eventstate->xy[0],
               window->eventstate->xy[1],
               IFACE_(state->split_factor > 0.0001f ? "Select Split" : "Split/Dock"));
    }
    else if (state->join_direction != SCREEN_DIR_NONE) {
      screen_draw_join_highlight(state->source, state->target);
      drag_tip(window,
               state->source,
               window->eventstate->xy[0],
               window->eventstate->xy[1],
               IFACE_("Join Areas"));
    }
    else {
      darken(state->source);
    }
    GPU_blend(GPU_BLEND_NONE);
    return;
  }
  if (!state->target || state->source == state->target || state->dock_target == SCREEN_DOCK_NONE) {
    GPU_blend(GPU_BLEND_NONE);
    return;
  }
  rctf rect;
  BLI_rctf_rcti_copy(&rect, &state->target->totrct);
  switch (state->dock_target) {
    case SCREEN_DOCK_LEFT:
      rect.xmax = interpf(rect.xmax, rect.xmin, state->factor);
      break;
    case SCREEN_DOCK_RIGHT:
      rect.xmin = interpf(rect.xmin, rect.xmax, state->factor);
      break;
    case SCREEN_DOCK_TOP:
      rect.ymin = interpf(rect.ymin, rect.ymax, state->factor);
      break;
    case SCREEN_DOCK_BOTTOM:
      rect.ymax = interpf(rect.ymax, rect.ymin, state->factor);
      break;
    default:
      break;
  }
  frame(&rect);
  drag_tip(
      window,
      state->source,
      state->current[0],
      state->current[1],
      IFACE_(state->dock_target == SCREEN_DOCK_CENTER ? "Replace this area" : "Move area here"));
  GPU_blend(GPU_BLEND_NONE);
}
