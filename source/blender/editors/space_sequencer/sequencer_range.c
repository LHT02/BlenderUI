/* SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spseq
 * Per-editor frame bounds. No scene mutation and no retained editor pointers.
 */

#include "DNA_scene_types.h"
#include "DNA_space_types.h"

#include "BLI_math_base.h"
#include "BLI_utildefines.h"

#include "ED_sequencer.h"

void ED_sequencer_timeline_range_set(SpaceSeq *sseq, int start, int end)
{
  if (!sseq) {
    return;
  }
  CLAMP(start, MINAFRAME, MAXFRAME);
  CLAMP(end, MINAFRAME, MAXFRAME);
  sseq->timeline_start = start;
  sseq->timeline_end = max_ii(start, end);
  sseq->flag |= SEQ_TIMELINE_LOCAL_RANGE;
}

void ED_sequencer_timeline_range_ensure(SpaceSeq *sseq, const Scene *scene)
{
  if (!sseq) {
    return;
  }
  if (!(sseq->flag & SEQ_TIMELINE_LOCAL_RANGE)) {
    ED_sequencer_timeline_range_set(sseq, scene ? scene->r.sfra : 1, scene ? scene->r.efra : 250);
  }
  else {
    /* Saved/custom DNA values are untrusted; normalize without changing scene data. */
    ED_sequencer_timeline_range_set(sseq, sseq->timeline_start, sseq->timeline_end);
  }
}

void ED_sequencer_timeline_range_get(const SpaceSeq *sseq,
                                    const Scene *scene,
                                    int *r_start,
                                    int *r_end)
{
  int start = scene ? scene->r.sfra : 1;
  int end = scene ? scene->r.efra : 250;
  if (sseq && (sseq->flag & SEQ_TIMELINE_LOCAL_RANGE)) {
    start = sseq->timeline_start;
    end = sseq->timeline_end;
  }
  CLAMP(start, MINAFRAME, MAXFRAME);
  CLAMP(end, MINAFRAME, MAXFRAME);
  *r_start = start;
  *r_end = max_ii(start, end);
}
