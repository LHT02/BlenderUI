/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2024 BLUI */

/** \file
 * \ingroup GHOST
 *
 * Windows shell context menu.
 *
 * A file browser is expected to show the real shell menu on right-click: the
 * same entries Explorer shows, including the ones installed by other programs
 * ("Open with", "Send to", "Scan with ...", version control overlays, and on
 * Windows 11 the extended verbs behind "Show more options").
 *
 * Blender has nothing like this - its file browser has its own small menu - so
 * the shell menu has to be hosted directly: bind to the item's parent folder,
 * ask it for an `IContextMenu`, let it populate an `HMENU`, show that, and
 * forward the chosen verb back through `InvokeCommand`.
 *
 * Like the drop source, this depends on the Windows SDK only, so
 * `blui/tools/shellmenu_selftest.cc` can build and inspect the menu with no
 * window and no CMake build.
 * See also: https://learn.microsoft.com/en-us/windows/win32/shell/how-to-create-a-shell-context-menu
 */

#pragma once

#include <stdbool.h>

#ifdef _WIN32

/**
 * Build the shell context menu for \a utf8_paths and report its item labels.
 *
 * Nothing is shown: this exists so the menu can be inspected without a window.
 * It exercises the whole COM path (parsing the paths, binding to the parent
 * folder, `GetUIObjectOf`, `QueryContextMenu`) which is where the mistakes are.
 *
 * \param utf8_paths: Array of NUL terminated UTF-8 file paths.
 * \param count: Number of entries in \a utf8_paths.
 * \param r_labels: Receives a newly allocated array of UTF-8 menu labels, in
 *        menu order. Separators come back as empty strings.
 * \param r_label_count: Receives the number of labels.
 * \return True on success.
 */
bool GHOST_ShellMenuWin32_EnumerateLabels(const char *const *utf8_paths,
                                          int count,
                                          char ***r_labels,
                                          int *r_label_count);

/** Free an array produced by #GHOST_ShellMenuWin32_EnumerateLabels. */
void GHOST_ShellMenuWin32_FreeLabels(char **labels, int count);

/**
 * Whether the shell's menu object for \a utf8_paths implements
 * `IContextMenu2` or `IContextMenu3`, and so expects its menu messages to be
 * forwarded while the menu is up.
 *
 * This is the difference between a menu whose top-level entries merely appear
 * and one whose extension submenus actually fill in: `QueryContextMenu`
 * produces the former, `WM_INITMENUPOPUP` forwarded to `HandleMenuMsg2()` the
 * latter. Exposed so a test can assert the forwarding path has a receiver
 * without opening a menu.
 *
 * \return True if the menu wants its messages forwarded.
 */
bool GHOST_ShellMenuWin32_SupportsMenuMessages(const char *const *utf8_paths, int count);

/**
 * Show the shell context menu for \a utf8_paths and invoke the chosen entry.
 *
 * Blocks while the menu is open, which is what `TrackPopupMenu` does.
 *
 * \param hwnd: Window that owns the menu.
 * \param utf8_paths: Files the menu acts on. They must share a parent folder.
 * \param count: Number of entries in \a utf8_paths.
 * \param screen_x: Screen coordinate to show the menu at.
 * \param screen_y: Screen coordinate to show the menu at.
 * \return True if the user picked an entry and it was invoked.
 */
bool GHOST_ShellMenuWin32_Popup(void *hwnd,
                                const char *const *utf8_paths,
                                int count,
                                int screen_x,
                                int screen_y);

/**
 * Ask the shell for the icon it shows for \a utf8_path, as RGBA pixels.
 *
 * This is how a shortcut gets its own icon: a `.lnk` displays the icon of what
 * it points at, which is what makes it recognisable, and resolving that is the
 * shell's job rather than something to parse out of the file. It works for any
 * path - the shell returns the icon registered for the extension.
 *
 * The icon is fetched through the system image list (`SHGetImageList`), not
 * `SHGFI_ICON`, because the latter only ever returns the small system icon.
 * Tiers are tried largest first and the caller scales down.
 *
 * \param r_pixels: Receives a newly allocated `width * height * 4` RGBA buffer,
 *        top row first. Free with #GHOST_ShellMenuWin32_FreeIconRgba.
 * \return True on success.
 */
bool GHOST_ShellMenuWin32_LoadFileIconRgba(const char *utf8_path,
                                           unsigned char **r_pixels,
                                           int *r_width,
                                           int *r_height);

/** Free a buffer produced by #GHOST_ShellMenuWin32_LoadFileIconRgba. */
void GHOST_ShellMenuWin32_FreeIconRgba(unsigned char *pixels);

#endif /* _WIN32 */
