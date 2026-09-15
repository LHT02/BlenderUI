# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright 2006 Blender Foundation

# ---------------------------------------------------------------------------
# BLUI stripping notes.
#
# BLUI is a file browsing / image viewing environment, not a 3D content
# creation suite, so this fork removes 3D subsystems. Before deleting an
# intern library, check that nothing still compiles against its headers:
#
#   "Guarded by a WITH_* option" does NOT mean "safe to delete".
#
# Several libraries here build a *stub* implementation when their feature is
# disabled, and the rest of Blender links that stub unconditionally:
#
#   opensubdiv : stub/opensubdiv_*_stub.cc, always linked. BKE_subdiv_*
#                includes opensubdiv_*_capi.h regardless of WITH_OPENSUBDIV.
#   libmv      : intern/stub.cc, always linked. BKE_tracking_* includes
#                libmv-capi.h regardless of WITH_LIBMV.
#   iksolver   : reached through ikplugin when WITH_IK_SOLVER is on.
#
# Deleting any of these produces "C1083: cannot open include file". `cycles`
# is safe to delete: nothing outside intern/cycles includes its headers.
# ---------------------------------------------------------------------------

# add_subdirectory(atomic)  # header only
add_subdirectory(atomic)
add_subdirectory(clog)
add_subdirectory(ghost)
add_subdirectory(guardedalloc)
add_subdirectory(libmv)
add_subdirectory(memutil)
add_subdirectory(opencolorio)
add_subdirectory(opensubdiv)
add_subdirectory(mikktspace)
add_subdirectory(eigen)
add_subdirectory(sky)

if(WITH_AUDASPACE)
  add_subdirectory(audaspace)
endif()

if(WITH_MOD_REMESH)
  add_subdirectory(dualcon)
endif()

if(WITH_IK_SOLVER)
  add_subdirectory(iksolver)
endif()

if(WITH_IK_ITASC)
  add_subdirectory(itasc)
endif()

if(WITH_CYCLES)
  add_subdirectory(cycles)
endif()

if(WITH_INTERNATIONAL)
  add_subdirectory(locale)
endif()

if(WITH_BULLET)
  add_subdirectory(rigidbody)
endif()

# only windows needs utf16 converter
if(WIN32)
  add_subdirectory(utfconv)
endif()

if(WITH_MOD_FLUID)
  add_subdirectory(mantaflow)
endif()

if(WITH_OPENVDB)
  add_subdirectory(openvdb)
endif()

if(WITH_QUADRIFLOW)
  add_subdirectory(quadriflow)
endif()

if(WITH_CODEC_FFMPEG)
  add_subdirectory(ffmpeg)
endif()

if(UNIX AND NOT APPLE)
  add_subdirectory(libc_compat)
endif()

if(WITH_RENDERDOC)
  add_subdirectory(renderdoc_dynload)
endif()

if(UNIX AND NOT APPLE)
  # Important this comes after "ghost" as it uses includes defined by GHOST's CMake.
  if(WITH_GHOST_WAYLAND AND WITH_GHOST_WAYLAND_DYNLOAD)
    add_subdirectory(wayland_dynload)
  endif()
endif()
