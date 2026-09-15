/* SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edundo
 */

#include <string.h>

#include "BLI_utildefines.h"

#include "ED_paint.h"
#include "ED_text.h"
#include "ED_undo.h"
#include "undo_intern.hh"

/* Keep last */
#include "BKE_undo_system.h"

void ED_undosys_type_init(void)
{
  /* BLUI registers undo only for the editors it kept. Blender's list also had
   * the edit-mode and paint-mode undo types - armature, curve, font, lattice,
   * metaball, mesh, curves, sculpt, particle and paint-curve. Every one of
   * those belongs to a 3D or paint editor that BLUI does not register, so none
   * of them could ever be pushed. Dropping them is what lets the data editors
   * underneath (lattice, metaball, curves, ...) stop being referenced from
   * here; each was otherwise reachable *only* through this registry and through
   * `space_view3d` / `object`.
   *
   * `BKE_UNDOSYS_TYPE_SCULPT`, `_PARTICLE` and `_PAINTCURVE` are left declared
   * and defined but never assigned, because `sculpt_undo.cc` and
   * `paint_curve_undo.cc` still compare against them. They become null and go
   * away with `sculpt_paint`. */

  /* Image editor. */
  BKE_UNDOSYS_TYPE_IMAGE = BKE_undosys_type_append(ED_image_undosys_type);

  /* Text editor. */
  BKE_UNDOSYS_TYPE_TEXT = BKE_undosys_type_append(ED_text_undosys_type);

  /* Keep global undo last (as a fallback). */
  BKE_UNDOSYS_TYPE_MEMFILE = BKE_undosys_type_append(ED_memfile_undosys_type);
}

void ED_undosys_type_free(void)
{
  BKE_undosys_type_free_all();
}
