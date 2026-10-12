/* SPDX-License-Identifier: GPL-2.0-or-later */
/** One temporary image per editor; release only after its last editor has stopped using it. */
#include "DNA_image_types.h"
#include "DNA_screen_types.h"
#include "BKE_lib_id.h"
#include "BKE_main.h"
#include "BKE_context.h"
#include "BLI_listbase.h"
#include "ED_image.h"
#include "ED_screen.h"
#include "RNA_access.h"
#include "RNA_define.h"
#include "WM_api.h"

static void release_unused(Main *bmain, Image *image)
{
  if (!image || !(image->flag & IMA_BLUI_TEMPORARY) || image->id.us > 1 || (image->id.flag & LIB_FAKEUSER)) {
    return;
  }
  LISTBASE_FOREACH (bScreen *, screen, &bmain->screens) {
    LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
      LISTBASE_FOREACH (SpaceLink *, space, &area->spacedata) {
        if (space->spacetype == SPACE_IMAGE && ((SpaceImage *)space)->image == image) {
          return;
        }
      }
    }
  }
  BKE_id_free(bmain, image);
}

void ED_image_document_set(Main *bmain, SpaceImage *space, Image *image)
{
  Image *previous = space->image;
  if (image) {
    image->flag |= IMA_BLUI_TEMPORARY;
  }
  ED_space_image_set(bmain, space, image, false);
  if (previous != image) {
    release_unused(bmain, previous);
  }
}

void ED_image_document_clear(Main *bmain, SpaceImage *space)
{
  ED_image_document_set(bmain, space, NULL);
}

void ED_image_document_collect(Main *bmain)
{
  LISTBASE_FOREACH_MUTABLE (Image *, image, &bmain->images) {
    release_unused(bmain, image);
  }
}

static int document_clear_exec(bContext *C, wmOperator *op)
{
  if (!RNA_boolean_get(op->ptr, "confirmed") && WM_blui_document_confirm(C, "IMAGE", NULL, NULL)) {
    return OPERATOR_FINISHED;
  }
  ED_image_document_clear(CTX_data_main(C), CTX_wm_space_image(C));
  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, NULL);
  return OPERATOR_FINISHED;
}

void IMAGE_OT_document_clear(wmOperatorType *ot)
{
  ot->name = "Close Image";
  ot->description = "Close the current temporary image after confirming unsaved changes";
  ot->idname = "IMAGE_OT_document_clear";
  ot->exec = document_clear_exec;
  ot->poll = ED_operator_image_active;
  PropertyRNA *prop = RNA_def_boolean(ot->srna, "confirmed", false, "Confirmed", "Close after confirmation");
  RNA_def_property_flag(prop, PROP_HIDDEN | PROP_SKIP_SAVE);
}
