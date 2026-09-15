/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2009 Blender Foundation */

/** \file
 * \ingroup edrend
 */

#include <cstdlib>

#include "BLI_utildefines.h"

#include "ED_render.h"

#include "WM_api.h"

#include "render_intern.hh" /* own include */

/***************************** render ***********************************/

void ED_operatortypes_render()
{
#ifdef WITH_FREESTYLE
#endif
  /* render_internal.c */
  WM_operatortype_append(RENDER_OT_view_show);
  WM_operatortype_append(RENDER_OT_render);
  WM_operatortype_append(RENDER_OT_view_cancel);
  WM_operatortype_append(RENDER_OT_shutter_curve_preset);
  /* render_opengl.c */
  WM_operatortype_append(RENDER_OT_opengl);
}
