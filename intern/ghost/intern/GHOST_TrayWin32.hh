/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/** \file
 * \ingroup GHOST
 *
 * Windows system tray icon.
 *
 * BLUI is meant to sit alongside the desktop shell, so it has to be reachable
 * without one of its windows being open: a tray icon whose menu can bring up a
 * specific component. Blender has no tray support of any kind, so this is
 * written from scratch.
 *
 * The menu does not run anything itself. Choosing an entry calls the handler
 * registered with #GHOST_TrayWin32_SetCommandHandler, which the GHOST system
 * uses to push a #GHOST_kEventTrayCommand event. The tray callback fires from
 * the Win32 message loop, where running application code directly would be
 * unsafe, so it only posts.
 *
 * Depends on the Windows SDK only.
 */

#pragma once

#ifdef _WIN32

/** One tray menu entry. A NULL \a label means a separator. */
typedef struct GHOST_TrayItem {
  const char *label;   /* UTF-8 */
  const char *command; /* UTF-8, handed back through the handler */
} GHOST_TrayItem;

/**
 * Create the tray icon, replacing any previous one.
 *
 * \param tooltip: UTF-8 tooltip, may be NULL.
 * \param items: Menu entries.
 * \param item_count: Number of entries in \a items.
 * \return True if the icon was added.
 */
bool GHOST_TrayWin32_Add(const char *tooltip, const GHOST_TrayItem *items, int item_count);

/** Remove the tray icon. Safe to call when none exists. */
void GHOST_TrayWin32_Remove(void);

/** True while an icon is installed. */
bool GHOST_TrayWin32_IsActive(void);

/** Handler invoked with the command string of the chosen entry. */
typedef void (*GHOST_TrayCommandFn)(const char *command, void *user_data);

/**
 * Set the handler. Called from the Win32 message loop, so it must not run
 * application code directly - posting an event is the expected thing to do.
 */
void GHOST_TrayWin32_SetCommandHandler(GHOST_TrayCommandFn handler, void *user_data);

#endif /* _WIN32 */
