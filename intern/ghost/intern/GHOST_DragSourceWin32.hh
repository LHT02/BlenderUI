/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/** \file
 * \ingroup GHOST
 *
 * OLE drop *source* for Windows.
 *
 * Blender 3.6 implements only the drop *target* half of OLE drag-and-drop
 * (#GHOST_DropTargetWin32, i.e. #IDropTarget): it can receive files dragged in
 * from other applications, but it cannot hand files to them. Dragging a file
 * out of the file browser into Explorer, an image editor or a chat client
 * therefore did nothing at all.
 *
 * This file adds the missing half: an `IDataObject` carrying `CF_HDROP` plus the
 * `IDropSource` that drives it through `DoDragDrop()`.
 *
 * The handle types below are deliberately opaque `void *` rather than `HGLOBAL`
 * and the interfaces are forward declared, so this header does not drag
 * `<windows.h>` into every translation unit that includes it.
 *
 * The implementation depends on nothing but the Windows SDK, so it can be
 * compiled on its own for testing - see `blui/tools/dragsource_selftest.cc`.
 */

#pragma once

#include "GHOST_Types.h"

#ifdef _WIN32

struct IDataObject;

/**
 * Build the `CF_HDROP` payload for a list of file paths.
 *
 * The payload is a `DROPFILES` header followed by a wide, double-NUL-terminated
 * list of paths, which is what the shell expects for `CF_HDROP` when
 * `DROPFILES::fWide` is set.
 *
 * \param utf8_paths: Array of NUL terminated UTF-8 paths.
 * \param count: Number of entries in \a utf8_paths.
 * \return An `HGLOBAL` owned by the caller (free it with `GlobalFree()`), or
 *         NULL on failure.
 */
void *GHOST_DragSourceWin32_CreateHDrop(const char *const *utf8_paths, int count);

/**
 * Read a `CF_HDROP` payload back into UTF-8 paths. Used by the self test.
 *
 * \param hdrop: Payload returned by #GHOST_DragSourceWin32_CreateHDrop.
 * \param r_paths: Receives a newly allocated array of UTF-8 strings.
 * \param r_count: Receives the number of strings in \a r_paths.
 * \return True on success.
 */
bool GHOST_DragSourceWin32_ReadHDrop(void *hdrop, char ***r_paths, int *r_count);

/** Free a path array produced by #GHOST_DragSourceWin32_ReadHDrop. */
void GHOST_DragSourceWin32_FreePaths(char **paths, int count);

/**
 * Create the `IDataObject` that a drag of these files would carry.
 *
 * Exposed separately from #GHOST_DragSourceWin32_StartDrag so the object can be
 * interrogated without a window or a real drag.
 *
 * \return An object with a reference owned by the caller (release with
 *         `Release()`), or NULL on failure.
 */
IDataObject *GHOST_DragSourceWin32_CreateDataObject(const char *const *utf8_paths, int count);

/**
 * Start an OLE drag of \a count files owned by \a hwnd.
 *
 * Blocks until the user drops the files or cancels, because `DoDragDrop()`
 * runs the OLE modal drag loop.
 *
 * \return GHOST_kSuccess if the files were handed to a drop target,
 *         GHOST_kFailure if the drag was cancelled or could not start.
 */
GHOST_TSuccess GHOST_DragSourceWin32_StartDrag(void *hwnd,
                                               const char *const *utf8_paths,
                                               int count);

#endif /* _WIN32 */
