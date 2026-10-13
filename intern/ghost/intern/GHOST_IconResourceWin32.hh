/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2026 BLUI */
#pragma once

#ifdef _WIN32
#  include <windows.h>
#  undef min
#  undef max

/** Read a shortcut's largest original icon resource, without resolving or launching its target.
 * The caller must initialize COM and destroy the returned, non-shared icon. */
HICON GHOST_Win32_LoadShortcutIconResource(const wchar_t *path);
#endif
