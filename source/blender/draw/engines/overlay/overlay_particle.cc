/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2019 Blender Foundation. */

/** \file
 * \ingroup draw_engine
 */

#include "DRW_render.h"

#include "DEG_depsgraph_query.h"

#include "DNA_particle_types.h"

#include "BKE_pointcache.h"

#include "overlay_private.hh"

/* -------------------------------------------------------------------- */
/** \name Particles
 * \{ */

void OVERLAY_particle_cache_init(OVERLAY_Data *vedata)
{
  OVERLAY_PassList *psl = vedata->psl;
  OVERLAY_PrivateData *pd = vedata->stl->pd;
  GPUShader *sh;
  DRWShadingGroup *grp;

  DRWState state = DRW_STATE_WRITE_COLOR | DRW_STATE_WRITE_DEPTH | DRW_STATE_DEPTH_LESS_EQUAL;
  DRW_PASS_CREATE(psl->particle_ps, state | pd->clipping_state);

  sh = OVERLAY_shader_particle_dot();
  pd->particle_dots_grp = grp = DRW_shgroup_create(sh, psl->particle_ps);
  DRW_shgroup_uniform_block(grp, "globalsBlock", G_draw.block_ubo);
  DRW_shgroup_uniform_texture(grp, "weightTex", G_draw.ramp);

  sh = OVERLAY_shader_particle_shape();
  pd->particle_shapes_grp = grp = DRW_shgroup_create(sh, psl->particle_ps);
  DRW_shgroup_uniform_block(grp, "globalsBlock", G_draw.block_ubo);
  DRW_shgroup_uniform_texture(grp, "weightTex", G_draw.ramp);
}

void OVERLAY_particle_cache_populate(OVERLAY_Data *vedata, Object *ob)
{
  OVERLAY_PrivateData *pd = vedata->stl->pd;

  LISTBASE_FOREACH (ParticleSystem *, psys, &ob->particlesystem) {
    if (!DRW_object_is_visible_psys_in_active_context(ob, psys)) {
      continue;
    }

    ParticleSettings *part = psys->part;
    int draw_as = (part->draw_as == PART_DRAW_REND) ? part->ren_as : part->draw_as;

    if (part->type == PART_HAIR) {
      /* Hairs should have been rendered by the render engine. */
      continue;
    }

    if (!ELEM(draw_as, PART_DRAW_NOT, PART_DRAW_OB, PART_DRAW_GR)) {
      struct GPUBatch *geom = DRW_cache_particles_get_dots(ob, psys);
      struct GPUBatch *shape = nullptr;
      DRWShadingGroup *grp;

      /* TODO(fclem): Here would be a good place for preemptive culling. */

      /* NOTE(fclem): Is color even useful in our modern context? */
      Material *ma = BKE_object_material_get_eval(ob, part->omat);
      float color[4] = {0.6f, 0.6f, 0.6f, part->draw_size};
      if (ma != nullptr) {
        copy_v3_v3(color, &ma->r);
      }

      switch (draw_as) {
        default:
        case PART_DRAW_DOT:
          grp = DRW_shgroup_create_sub(pd->particle_dots_grp);
          DRW_shgroup_uniform_vec4_copy(grp, "ucolor", color);
          DRW_shgroup_call(grp, geom, nullptr);
          break;
        case PART_DRAW_AXIS:
        case PART_DRAW_CIRC:
        case PART_DRAW_CROSS:
          grp = DRW_shgroup_create_sub(pd->particle_shapes_grp);
          DRW_shgroup_uniform_vec4_copy(grp, "ucolor", color);
          shape = DRW_cache_particles_get_prim(draw_as);
          DRW_shgroup_call_instances_with_attrs(grp, nullptr, shape, geom);
          break;
      }
    }
  }
}

void OVERLAY_particle_draw(OVERLAY_Data *vedata)
{
  OVERLAY_PassList *psl = vedata->psl;

  DRW_draw_pass(psl->particle_ps);
}

/** \} */
