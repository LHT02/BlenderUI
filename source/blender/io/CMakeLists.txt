# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright 2020 Blender Foundation

# BLUI: the 3D scene interchange importers/exporters (Alembic, USD, Collada,
# Wavefront OBJ, PLY, STL, grease pencil) were deleted from this fork, as was
# the `common` helper library that only they used. Only the AVI container
# codec, which the sequencer needs, remains.

if(WITH_CODEC_AVI)
  add_subdirectory(avi)
endif()
