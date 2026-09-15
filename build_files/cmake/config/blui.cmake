# SPDX-License-Identifier: GPL-2.0-or-later
#
# BLUI build configuration.
#
# BLUI is a standalone file-browsing / image-viewing / text-editing environment
# built on the Blender 3.6 code base. It is *not* a 3D content creation suite,
# so every subsystem that exists only to model, sculpt, simulate, render or
# exchange 3D data is switched off here.
#
# This is the *first* stage of stripping BLUI down to its UI framework: the
# source is still present, but the 3D subsystems are not compiled at all. Once
# this configuration builds and runs reliably it becomes safe to physically
# delete the corresponding source trees.
#
# Kept (required by the BLUI components):
#   - GHOST + window manager + DNA/RNA  -> application shell and UI framework
#   - editors                           -> file browser, image, text, sequencer,
#                                          preferences
#   - image codecs                      -> PNG/JPEG/TIFF/OpenEXR/JPEG2000/
#                                          WebP/Cineon/DDS
#   - FFmpeg                            -> video decode for the sequencer and
#                                          video thumbnails
#   - audio (audaspace/OpenAL/sndfile)  -> sequencer playback
#   - Python                            -> UI scripts, operators, preferences
#   - freetype / international / IME    -> text editor, non-latin input
#   - OpenColorIO                       -> colour management for image display
#
# Usage:
#   cmake -C build_files/cmake/config/blui.cmake -S . -B ../build

# ---------------------------------------------------------------------------
# 3D content creation, simulation and interchange: OFF
# ---------------------------------------------------------------------------

# Render engines.
set(WITH_CYCLES              OFF CACHE BOOL "" FORCE)
set(WITH_FREESTYLE           OFF CACHE BOOL "" FORCE)
set(WITH_OPENIMAGEDENOISE    OFF CACHE BOOL "" FORCE)

# Geometry / simulation.
set(WITH_BULLET              OFF CACHE BOOL "" FORCE)
set(WITH_OPENSUBDIV          OFF CACHE BOOL "" FORCE)
set(WITH_OPENVDB             OFF CACHE BOOL "" FORCE)
set(WITH_NANOVDB             OFF CACHE BOOL "" FORCE)
set(WITH_MOD_FLUID           OFF CACHE BOOL "" FORCE)
set(WITH_MOD_OCEANSIM        OFF CACHE BOOL "" FORCE)
set(WITH_MOD_REMESH          OFF CACHE BOOL "" FORCE)
set(WITH_QUADRIFLOW          OFF CACHE BOOL "" FORCE)

# Rigging / motion tracking.
set(WITH_IK_ITASC            OFF CACHE BOOL "" FORCE)
set(WITH_IK_SOLVER           OFF CACHE BOOL "" FORCE)
set(WITH_LIBMV               OFF CACHE BOOL "" FORCE)

# 3D scene interchange.
set(WITH_ALEMBIC             OFF CACHE BOOL "" FORCE)
set(WITH_USD                 OFF CACHE BOOL "" FORCE)
set(WITH_MATERIALX           OFF CACHE BOOL "" FORCE)
set(WITH_OPENCOLLADA         OFF CACHE BOOL "" FORCE)
set(WITH_DRACO               OFF CACHE BOOL "" FORCE)

# Mesh / curve import-export.
set(WITH_IO_PLY              OFF CACHE BOOL "" FORCE)
set(WITH_IO_STL              OFF CACHE BOOL "" FORCE)
set(WITH_IO_WAVEFRONT_OBJ    OFF CACHE BOOL "" FORCE)
set(WITH_IO_GPENCIL          OFF CACHE BOOL "" FORCE)

# Vector / PDF / hardware specific.
set(WITH_POTRACE             OFF CACHE BOOL "" FORCE)
set(WITH_HARU                OFF CACHE BOOL "" FORCE)
set(WITH_XR_OPENXR           OFF CACHE BOOL "" FORCE)
set(WITH_LLVM                OFF CACHE BOOL "" FORCE)
set(WITH_BLENDER_THUMBNAILER OFF CACHE BOOL "" FORCE)
set(WITH_INPUT_NDOF          OFF CACHE BOOL "" FORCE)

# ---------------------------------------------------------------------------
# Media, UI and scripting: ON
#
# These are stated explicitly rather than left to the platform default so the
# BLUI feature set is reproducible on every machine.
# ---------------------------------------------------------------------------

set(WITH_PYTHON              ON  CACHE BOOL "" FORCE)
set(WITH_CODEC_FFMPEG        ON  CACHE BOOL "" FORCE)
set(WITH_CODEC_AVI           ON  CACHE BOOL "" FORCE)
set(WITH_CODEC_SNDFILE       ON  CACHE BOOL "" FORCE)
set(WITH_AUDASPACE           ON  CACHE BOOL "" FORCE)
set(WITH_IMAGE_OPENEXR       ON  CACHE BOOL "" FORCE)
set(WITH_IMAGE_OPENJPEG      ON  CACHE BOOL "" FORCE)
set(WITH_IMAGE_CINEON        ON  CACHE BOOL "" FORCE)
set(WITH_IMAGE_WEBP          ON  CACHE BOOL "" FORCE)
set(WITH_IMAGE_DDS           ON  CACHE BOOL "" FORCE)
set(WITH_OPENCOLORIO         ON  CACHE BOOL "" FORCE)
set(WITH_INTERNATIONAL       ON  CACHE BOOL "" FORCE)
set(WITH_INPUT_IME           ON  CACHE BOOL "" FORCE)
set(WITH_FREETYPE            ON  CACHE BOOL "" FORCE)

# ---------------------------------------------------------------------------
# Build hygiene
# ---------------------------------------------------------------------------

# Build info embeds the git revision, which forces a relink of the executable
# on every commit. Disabled so iteration on the UI stays fast.
set(WITH_BUILDINFO           OFF CACHE BOOL "" FORCE)
# Blender's CMake default is ON, which makes every failed BLI_assert call
# abort() - fine for a development build, wrong for something we hand to a user
# as a file browser. Blender's own release profile turns it off; so does BLUI's.
set(WITH_ASSERT_ABORT        OFF CACHE BOOL "" FORCE)
# Bundle the CRT only when producing a redistributable package; not needed for
# development builds and it requires the CRT merge modules to be installed.
set(WITH_WINDOWS_BUNDLE_CRT  OFF CACHE BOOL "" FORCE)
set(WITH_DOC_MANPAGE         OFF CACHE BOOL "" FORCE)
set(WITH_GTESTS              OFF CACHE BOOL "" FORCE)
