/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2008 Blender Foundation. */

/** \file
 * \ingroup spapi
 */

#include <stdlib.h>

#include "MEM_guardedalloc.h"

#include "BLI_blenlib.h"
#include "BLI_utildefines.h"

#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_context.h"
#include "BKE_screen.h"

#include "GPU_state.h"

#include "UI_interface.h"
#include "UI_view2d.h"

#include "ED_anim_api.h"
#include "ED_armature.h"
#include "ED_asset.h"
#include "ED_clip.h"
#include "ED_curve.h"
#include "ED_curves.h"
#include "ED_curves_sculpt.h"
#include "ED_fileselect.h"
#include "ED_geometry.h"
#include "ED_gizmo_library.h"
#include "ED_gpencil_legacy.h"
#include "ED_lattice.h"
#include "ED_markers.h"
#include "ED_mask.h"
#include "ED_mball.h"
#include "ED_mesh.h"
#include "ED_node.h"
#include "ED_object.h"
#include "ED_paint.h"
#include "ED_physics.h"
#include "ED_render.h"
#include "ED_scene.h"
#include "ED_screen.h"
#include "ED_sculpt.h"
#include "ED_sequencer.h"
#include "ED_sound.h"
#include "ED_space_api.h"
#include "ED_transform.h"
#include "ED_userpref.h"
#include "ED_util.h"
#include "ED_uvedit.h"

void ED_spacetypes_init(void)
{
  /* UI unit is a variable, may be used in some space type initialization. */
  U.widget_unit = 20;

  /* Create space types.
   *
   * BLUI registers only the editors its own component set is made of. The
   * editors that exist to model, sculpt, animate, shade or track have no
   * workspace here and no entry in the editor-type menu, so they are never
   * created at all - and an unregistered space type cannot be reached from the
   * editor-type menu, from the operator search menu, or from Python.
   *
   * Four registrations are kept for machinery rather than for a user:
   * `script` (SPACE_SCRIPT) is a deprecated space id whose only purpose is to
   * carry the script operators, `info` is the space type the .blend reader
   * falls back to for an area with no space data at all, and `topbar` /
   * `statusbar` are the global areas. None of them is offered as an editor. */
  ED_spacetype_image();
  ED_spacetype_info();
  ED_spacetype_file();
  ED_spacetype_script();
  ED_spacetype_text();
  ED_spacetype_sequencer();
  ED_spacetype_console();
  ED_spacetype_userpref();
  ED_spacetype_statusbar();
  ED_spacetype_topbar();

  /* Register operator types for screen and all spaces. */
  ED_operatortypes_userpref();
  ED_operatortypes_workspace();
  ED_operatortypes_screen();
  ED_operatortypes_anim();
  ED_operatortypes_animchannels();
  ED_operatortypes_asset();
  ED_operatortypes_gpencil();
  ED_operatortypes_object();
  ED_operatortypes_paint();
  ED_operatortypes_marker();
  ED_operatortypes_sound();
  ED_operatortypes_render();
  ED_operatortypes_edutils();

  /* Transform is a shared facility, not a 3D-view one: the video sequencer's
   * slide tool is the macro `TRANSFORM_OT_seq_slide`. Blender registers these
   * from the 3D viewport's space type callback - which BLUI does not create -
   * so they are registered here instead. Without this the sequencer's slide
   * macro silently loses its operator. */
  transform_operatortypes();

  ED_operatortypes_view2d();
  ED_operatortypes_ui();

  ED_screen_user_menu_register();

  ED_uilisttypes_ui();

  /* Gizmo types. */
  ED_gizmotypes_button_2d();
  ED_gizmotypes_dial_3d();
  ED_gizmotypes_move_3d();
  ED_gizmotypes_arrow_3d();
  ED_gizmotypes_preselect_3d();
  ED_gizmotypes_primitive_3d();
  ED_gizmotypes_blank_3d();
  ED_gizmotypes_cage_2d();
  ED_gizmotypes_cage_3d();
  ED_gizmotypes_snap_3d();

  /* Register types for operators and gizmos. */
  const ListBase *spacetypes = BKE_spacetypes_list();
  LISTBASE_FOREACH (const SpaceType *, type, spacetypes) {
    /* Initialize gizmo types first, operator types need them. */
    if (type->gizmos) {
      type->gizmos();
    }
    if (type->operatortypes) {
      type->operatortypes();
    }
  }
}

void ED_spacemacros_init(void)
{
  /* Macros must go last since they reference other operators.
   * They need to be registered after python operators too.
   *
   * BLUI registers macros only for the components it keeps. Eleven have come
   * out: node, action, graph, nla, metaball, armature, curve, clip, mask, mesh,
   * uv and object - twelve, counting object, which was the last.
   *
   * Each had to be removed **together with the keymap data that names it**, and
   * this is the part that cannot be worked out by reading.
   * `bl_keymap_utils/io.py` walks a macro's nested properties with
   * `property_unset()`, which *raises* where the flat case only warns, so a
   * single keymap entry naming a macro whose registration is gone aborts the
   * whole key configuration load - BLUI then starts with 7 keymaps instead of
   * 135, and Ctrl+S does nothing. The entries that had to come out of
   * `keymap_data/blender_default.py` were:
   *
   *   mesh.loopcut_slide, mesh.offset_edge_loops_slide   TRANSFORM_OT_edge_slide
   *   mesh.rip_move (V and Alt+V)                        MESH_OT_rip
   *   uv.rip_move (Image Editor Rip Region tool)         TRANSFORM_OT_translate
   *
   * Note the third: `TRANSFORM_OT_translate` *is* registered, and looks
   * harmless. It only breaks as a nested macro sub-property. Grepping for
   * nested property lists found three candidates and none of them was that one;
   * the traceback named it in a line. `check_keymap_config.py` says whether the
   * configuration survived, the traceback says which entry killed it, and both
   * are needed.
   *
   * The four left - file, sequencer, paint, gpencil - belong to components BLUI
   * keeps, so they stay. */
  ED_operatormacros_file();
  ED_operatormacros_sequencer();
  ED_operatormacros_gpencil();

  /* Register dropboxes (can use macros). */
  ED_dropboxes_ui();
  const ListBase *spacetypes = BKE_spacetypes_list();
  LISTBASE_FOREACH (const SpaceType *, type, spacetypes) {
    if (type->dropboxes) {
      type->dropboxes();
    }
  }
}

void ED_spacetypes_keymap(wmKeyConfig *keyconf)
{
  ED_keymap_screen(keyconf);
  ED_keymap_anim(keyconf);
  ED_keymap_animchannels(keyconf);
  ED_keymap_gpencil(keyconf);
  ED_keymap_object(keyconf);
  ED_keymap_paint(keyconf);
  ED_keymap_marker(keyconf);

  ED_keymap_view2d(keyconf);
  ED_keymap_ui(keyconf);

  ED_keymap_transform(keyconf);

  const ListBase *spacetypes = BKE_spacetypes_list();
  LISTBASE_FOREACH (const SpaceType *, type, spacetypes) {
    if (type->keymap) {
      type->keymap(keyconf);
    }
    LISTBASE_FOREACH (ARegionType *, region_type, &type->regiontypes) {
      if (region_type->keymap) {
        region_type->keymap(keyconf);
      }
    }
  }
}

/* ********************** Custom Draw Call API ***************** */

typedef struct RegionDrawCB {
  struct RegionDrawCB *next, *prev;

  void (*draw)(const struct bContext *, struct ARegion *, void *);
  void *customdata;

  int type;

} RegionDrawCB;

void *ED_region_draw_cb_activate(ARegionType *art,
                                 void (*draw)(const struct bContext *, struct ARegion *, void *),
                                 void *customdata,
                                 int type)
{
  RegionDrawCB *rdc = MEM_callocN(sizeof(RegionDrawCB), "RegionDrawCB");

  BLI_addtail(&art->drawcalls, rdc);
  rdc->draw = draw;
  rdc->customdata = customdata;
  rdc->type = type;

  return rdc;
}

bool ED_region_draw_cb_exit(ARegionType *art, void *handle)
{
  LISTBASE_FOREACH (RegionDrawCB *, rdc, &art->drawcalls) {
    if (rdc == (RegionDrawCB *)handle) {
      BLI_remlink(&art->drawcalls, rdc);
      MEM_freeN(rdc);
      return true;
    }
  }
  return false;
}

static void ed_region_draw_cb_draw(const bContext *C, ARegion *region, ARegionType *art, int type)
{
  LISTBASE_FOREACH_MUTABLE (RegionDrawCB *, rdc, &art->drawcalls) {
    if (rdc->type == type) {
      rdc->draw(C, region, rdc->customdata);

      /* This is needed until we get rid of BGL which can change the states we are tracking. */
      GPU_bgl_end();
    }
  }
}

void ED_region_draw_cb_draw(const bContext *C, ARegion *region, int type)
{
  ed_region_draw_cb_draw(C, region, region->type, type);
}

void ED_region_surface_draw_cb_draw(ARegionType *art, int type)
{
  ed_region_draw_cb_draw(NULL, NULL, art, type);
}

void ED_region_draw_cb_remove_by_type(ARegionType *art, void *draw_fn, void (*free)(void *))
{
  LISTBASE_FOREACH_MUTABLE (RegionDrawCB *, rdc, &art->drawcalls) {
    if (rdc->draw == draw_fn) {
      if (free) {
        free(rdc->customdata);
      }
      BLI_remlink(&art->drawcalls, rdc);
      MEM_freeN(rdc);
    }
  }
}

/* ********************* space template *********************** */
/* forward declare */
void ED_spacetype_xxx(void);

/* allocate and init some vars */
static SpaceLink *xxx_create(const ScrArea *UNUSED(area), const Scene *UNUSED(scene))
{
  return NULL;
}

/* not spacelink itself */
static void xxx_free(SpaceLink *UNUSED(sl)) {}

/* spacetype; init callback for usage, should be re-doable. */
static void xxx_init(wmWindowManager *UNUSED(wm), ScrArea *UNUSED(area))
{

  /* link area to SpaceXXX struct */

  /* define how many regions, the order and types */

  /* add types to regions */
}

static SpaceLink *xxx_duplicate(SpaceLink *UNUSED(sl))
{

  return NULL;
}

static void xxx_operatortypes(void)
{
  /* register operator types for this space */
}

static void xxx_keymap(wmKeyConfig *UNUSED(keyconf))
{
  /* add default items to keymap */
}

/* only called once, from screen/spacetypes.c */
void ED_spacetype_xxx(void)
{
  static SpaceType st;

  st.spaceid = SPACE_VIEW3D;

  st.create = xxx_create;
  st.free = xxx_free;
  st.init = xxx_init;
  st.duplicate = xxx_duplicate;
  st.operatortypes = xxx_operatortypes;
  st.keymap = xxx_keymap;

  BKE_spacetype_register(&st);
}

/* ****************************** end template *********************** */
