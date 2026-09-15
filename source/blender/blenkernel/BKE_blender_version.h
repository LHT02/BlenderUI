/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#include "BLI_utildefines.h"

#ifdef __cplusplus
extern "C" {
#endif

/** \file
 * \ingroup bke
 */

/**
 * The lines below use regex from scripts to extract their values,
 * Keep this in mind when modifying this file and keep this comment above the defines.
 *
 * \note Use #STRINGIFY() rather than defining with quotes.
 */

/* Blender major and minor version. */
#define BLENDER_VERSION 306
/* Blender patch version for bugfix releases. */
#define BLENDER_VERSION_PATCH 23
/** Blender release cycle stage: alpha/beta/rc/release. */
#define BLENDER_VERSION_CYCLE release

/* Blender file format version. */
#define BLENDER_FILE_VERSION BLENDER_VERSION
#define BLENDER_FILE_SUBVERSION 14

/* -------------------------------------------------------------------- */
/** \name BLUI product identity
 *
 * BLUI is a standalone application built from the Blender 3.6 source tree.
 *
 * The product version is deliberately kept separate from #BLENDER_VERSION:
 * - #BLENDER_VERSION tracks the Blender file/DNA generation, which the
 *   `.blend` reader, the DNA structs and the legacy versioning code depend on.
 *   Changing it would silently change file-format behaviour.
 * - #BLUI_VERSION is the version users see (window title, `--version`,
 *   splash screen) and it names the user configuration directory.
 *
 * Keeping them apart means BLUI can version itself independently without
 * disturbing the compatibility machinery it inherited.
 * \{ */

/** BLUI product version, encoded as `major * 100 + minor` (e.g. 100 is "1.0"). */
#define BLUI_VERSION 100
/** BLUI product patch version. */
#define BLUI_VERSION_PATCH 0
/** BLUI release cycle stage: alpha/beta/rc/release. */
#define BLUI_VERSION_CYCLE release

/** User readable BLUI version, e.g. `"1.0.0"`. */
#define BLUI_VERSION_STRING "1.0.0"
/**
 * Directory name used below the application data root to hold this version's
 * user files, e.g. `%APPDATA%/BLUI/1.0`.
 *
 * Deliberately *not* the Blender version: BLUI must never share configuration
 * with a Blender installation.
 */
#define BLUI_VERSION_DIR "1.0"

/** Product name used for window titles, message boxes and about dialogs. */
#define BLUI_PRODUCT_NAME "BLUI"

/** \} */

/* Minimum Blender version that supports reading file written with the current
 * version. Older Blender versions will test this and cancel loading the file, showing a warning to
 * the user.
 *
 * See https://wiki.blender.org/wiki/Process/Compatibility_Handling for details. */
#define BLENDER_FILE_MIN_VERSION 303
#define BLENDER_FILE_MIN_SUBVERSION 06

/** User readable version string. */
const char *BKE_blender_version_string(void);

/* Returns true when version cycle is alpha, otherwise (beta, rc) returns false. */
bool BKE_blender_version_is_alpha(void);

/** Fill in given string buffer with user-readable formated file version and subversion (if
 * provided).
 *
 * \param str_buff a char buffer where the formated string is written, minimal recommended size is
 * 8, or 16 if subversion is provided.
 *
 * \param file_subversion the file subversion, if given value < 0, it is ignored, and only the
 * `file_version` is used. */
void BKE_blender_version_blendfile_string_from_values(char *str_buff,
                                                      const size_t str_buff_len,
                                                      const short file_version,
                                                      const short file_subversion);

#ifdef __cplusplus
}
#endif
