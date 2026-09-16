/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2001-2002 NaN Holding BV. All rights reserved. */

#pragma once

/** \file
 * \ingroup bli
 * \brief Compatibility-like things for windows.
 */

#ifndef _WIN32
#  error "This include is for Windows only!"
#endif

#include "BLI_sys_types.h"

#define WIN32_LEAN_AND_MEAN

#include <windows.h>

#undef rad
#undef rad1
#undef rad2
#undef rad3
#undef vec
#undef rect
#undef rct1
#undef rct2

#undef small

/* These definitions are also in BLI_math for simplicity. */

#ifdef __cplusplus
extern "C" {
#endif

#if !defined(_USE_MATH_DEFINES)
#  define _USE_MATH_DEFINES
#endif

#define MAXPATHLEN MAX_PATH

#ifndef S_ISREG
#  define S_ISREG(x) (((x)&_S_IFREG) == _S_IFREG)
#endif
#ifndef S_ISDIR
#  define S_ISDIR(x) (((x)&_S_IFDIR) == _S_IFDIR)
#endif

#if defined(_MSC_VER)
#  define R_OK 4
#  define W_OK 2
/* Not accepted by `access()` on windows. */
//#  define X_OK    1
#  define F_OK 0
#endif

typedef unsigned int mode_t;

#ifndef _SSIZE_T_
#  define _SSIZE_T_
/* python uses HAVE_SSIZE_T */
#  ifndef HAVE_SSIZE_T
#    define HAVE_SSIZE_T 1
typedef SSIZE_T ssize_t;
#  endif
#endif

/** Directory reading compatibility with UNIX. */
struct dirent {
  int d_ino;
  int d_off;
  unsigned short d_reclen;
  char *d_name;
};

/** Intentionally opaque to users. */
typedef struct __dirstream DIR;

DIR *opendir(const char *path);
struct dirent *readdir(DIR *dp);
int closedir(DIR *dp);
const char *dirname(char *path);

/* Windows utility functions. */

bool BLI_windows_register_blend_extension(bool background);
/**
 * Set the `root_dir` to the default root directory on MS-Windows,
 * The string is guaranteed to be set with a length of 3 & null terminated,
 * using a fall-back in case the root directory can't be found.
 */
void BLI_windows_get_default_root_dir(char root_dir[4]);
int BLI_windows_get_executable_dir(char r_dirpath[/*FILE_MAXDIR*/]);

/* ShellExecute Helpers. */

bool BLI_windows_external_operation_supported(const char *filepath, const char *operation);
bool BLI_windows_external_operation_execute(const char *filepath, const char *operation);

/* Shell icon helpers. */

/**
 * Ask the shell for the icon it would show for \a filepath, as RGBA pixels.
 *
 * This is how a shortcut gets its own icon: a `.lnk` displays the icon of
 * whatever it points at, which is what makes it recognisable, and resolving
 * that is the shell's job rather than something to parse out of the file. It
 * works for any path - the shell returns the icon registered for the
 * extension - but it costs a shell round trip per call, so call it for the
 * files that need it rather than for every entry in a listing.
 *
 * \param r_pixels: Receives a newly allocated `width * height * 4` RGBA buffer,
 *        top row first. Free with #BLI_windows_file_icon_free.
 * \param r_width: Receives the icon width in pixels.
 * \param r_height: Receives the icon height in pixels.
 * \return True on success.
 */
bool BLI_windows_file_icon_load(const char *filepath,
                                unsigned char **r_pixels,
                                int *r_width,
                                int *r_height);

/** Free a buffer produced by #BLI_windows_file_icon_load. */
void BLI_windows_file_icon_free(unsigned char *pixels);

#ifdef __cplusplus
}
#endif
