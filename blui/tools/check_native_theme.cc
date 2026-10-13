/* SPDX-License-Identifier: GPL-2.0-or-later
 * Compile this standalone Win32 fixture with MSVC, user32/gdi32/advapi32/dwmapi/shcore/shell32.
 * It substitutes theme reads inside one translation unit only. It never changes system colors
 * or the user's registry. All windows, timers, and tray icons belong to this fixture process. */

#include <cstdio>
#include <cstring>
#include <windows.h>

#include "../../intern/ghost/intern/GHOST_ThemeWin32.hh"
#include "../../intern/ghost/intern/GHOST_TrayMenuWin32.hh"

static DWORD app_light = 0;
static DWORD shell_light = 1;

static LSTATUS WINAPI
fixture_theme_read(HKEY, LPCWSTR, LPCWSTR value, DWORD, LPDWORD, PVOID data, LPDWORD size)
{
  if (!data || !size || *size < sizeof(DWORD)) {
    return ERROR_MORE_DATA;
  }
  *static_cast<DWORD *>(data) = wcscmp(value, L"SystemUsesLightTheme") == 0 ? shell_light :
                                                                              app_light;
  *size = sizeof(DWORD);
  return ERROR_SUCCESS;
}

/* Test the production implementation with read-only in-process preferences. */
#define RegGetValueW fixture_theme_read
#include "../../intern/ghost/intern/GHOST_ThemeWin32.cc"
#undef RegGetValueW
#include "../../intern/ghost/intern/GHOST_TrayMenuWin32.cc"
#include "../../intern/ghost/intern/GHOST_TrayWin32.cc"

static int failures = 0;
static int draw_count = 0;
static GHOST_TrayMenuWin32 *active_menu = nullptr;
static int command_count = 0;

static void check(bool value, const char *label)
{
  printf("%s %s\n", value ? "PASS" : "FAIL", label);
  if (!value) {
    failures++;
  }
}

static LRESULT CALLBACK fixture_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
  if (message == WM_MEASUREITEM && active_menu) {
    return active_menu->measure(*reinterpret_cast<MEASUREITEMSTRUCT *>(lparam));
  }
  if (message == WM_DRAWITEM && active_menu) {
    draw_count++;
    return active_menu->draw(*reinterpret_cast<DRAWITEMSTRUCT *>(lparam));
  }
  if (message == WM_TIMER) {
    KillTimer(hwnd, 1);
    EndMenu();
    return 0;
  }
  return DefWindowProcW(hwnd, message, wparam, lparam);
}

static void fixture_command(const char *command, void *)
{
  if (strcmp(command, "fixture-open") == 0) {
    command_count++;
  }
}

static BOOL CALLBACK find_tray(HWND hwnd, LPARAM result)
{
  DWORD pid;
  GetWindowThreadProcessId(hwnd, &pid);
  wchar_t type[128];
  if (pid == GetCurrentProcessId() && GetClassNameW(hwnd, type, 128) &&
      wcscmp(type, L"BLUI_TrayWindow") == 0)
  {
    *reinterpret_cast<HWND *>(result) = hwnd;
    return FALSE;
  }
  return TRUE;
}

int main()
{
  SetProcessDPIAware();
  const auto app = GHOST_ThemeWin32_Palette(false);
  const auto shell = GHOST_ThemeWin32_Palette(true);
  check(app.dark && !shell.dark, "app and shell preferences are separate");

  WNDCLASSW type = {};
  type.hInstance = GetModuleHandleW(nullptr);
  type.lpfnWndProc = fixture_proc;
  type.lpszClassName = L"BLUI_ThemeFixture";
  RegisterClassW(&type);
  HWND window = CreateWindowExW(WS_EX_TOOLWINDOW,
                                type.lpszClassName,
                                L"BLUI theme fixture",
                                WS_OVERLAPPED,
                                0,
                                0,
                                1,
                                1,
                                nullptr,
                                nullptr,
                                type.hInstance,
                                nullptr);
  check(window != nullptr, "fixture owner created");
  if (!window) {
    return 1;
  }

  HDC owner_dc = GetDC(window);
  HDC paint = CreateCompatibleDC(owner_dc);
  HBITMAP bitmap = CreateCompatibleBitmap(owner_dc, 1024, 128);
  HGDIOBJ previous = SelectObject(paint, bitmap);
  const std::vector<std::wstring> labels = {L"Files", L"图像", L"", L"Quit BLUI"};

  for (DWORD light = 0; light < 2; light++) {
    shell_light = light;
    const auto expected = GHOST_ThemeWin32_Palette(true);
    GHOST_TrayMenuWin32 menu(window, labels);
    MEASUREITEMSTRUCT size = {};
    size.CtlType = ODT_MENU;
    size.itemData = 1;
    check(menu.measure(size) && size.itemWidth >= 180 && size.itemHeight >= 16,
          "native font and DPI menu measurement");
    DRAWITEMSTRUCT draw = {};
    draw.CtlType = ODT_MENU;
    draw.itemData = 1;
    draw.hDC = paint;
    draw.rcItem = {0, 0, LONG(size.itemWidth), LONG(size.itemHeight)};
    check(menu.draw(draw) && GetPixel(paint, 1, 1) == expected.background,
          light ? "light popup uses light pixels" : "dark popup uses dark pixels");
    draw.itemState = ODS_SELECTED;
    check(menu.draw(draw) && GetPixel(paint, 1, 1) == expected.selected_background,
          "selected popup uses native accent contrast");
    draw.itemState = ODS_SELECTED | ODS_DISABLED;
    check(menu.draw(draw) && GetPixel(paint, 1, 1) == expected.background,
          "disabled menu item is not highlighted");
    draw.itemData = 999;
    check(!menu.draw(draw), "invalid item data is rejected");
    size.itemData = 3;
    check(menu.measure(size) && size.itemHeight < draw.rcItem.bottom,
          "separator has a compact non-command row");
    draw.itemData = 3;
    draw.rcItem.bottom = LONG(size.itemHeight);
    draw.itemState = 0;
    check(menu.draw(draw) &&
              GetPixel(paint, LONG(size.itemWidth) / 2, LONG(size.itemHeight) / 2) ==
                  expected.separator,
          "separator line follows the current shell palette");

    active_menu = &menu;
    SetTimer(window, 1, 120, nullptr);
    menu.show(window);
    active_menu = nullptr;
  }
  check(draw_count >= 4, "real TrackPopupMenu dispatches owner drawing");
  const DWORD handles = GetGuiResources(GetCurrentProcess(), GR_GDIOBJECTS);
  for (int cycle = 0; cycle < 100; cycle++) {
    GHOST_TrayMenuWin32 menu(window, labels);
  }
  check(GetGuiResources(GetCurrentProcess(), GR_GDIOBJECTS) <= handles + 1,
        "menu reconstruction does not leak GDI resources");

  GHOST_TrayWin32_SetCommandHandler(fixture_command, nullptr);
  const GHOST_TrayItem entries[] = {{"Open fixture", "fixture-open"}, {nullptr, nullptr}};
  check(GHOST_TrayWin32_Add("BLUI theme fixture", entries, 2), "fixture tray icon installed");
  HWND tray = nullptr;
  EnumWindows(find_tray, reinterpret_cast<LPARAM>(&tray));
  check(tray != nullptr, "fixture tray owner found by its own process ID");
  if (tray) {
    SendMessageW(tray, WM_APP + 1, 0, NIN_SELECT);
    check(command_count == 1, "first tray activation works before opening the menu");
    SendMessageW(tray, WM_THEMECHANGED, 0, 0);
    SendMessageW(tray, WM_SETTINGCHANGE, 0, 0);
    check(GHOST_TrayWin32_IsActive(), "null theme notification preserves the tray");
    SendMessageW(tray, WM_APP + 1, 0, NIN_KEYSELECT);
    check(command_count == 2, "version 4 keyboard activation works");
    NOTIFYICONDATAW own_icon = {};
    own_icon.cbSize = sizeof(own_icon);
    own_icon.hWnd = tray;
    own_icon.uID = 1;
    /* Remove only this fixture's icon to reproduce a shell restart. Never restart Explorer
     * or remove another application's notification icon. */
    check(Shell_NotifyIconW(NIM_DELETE, &own_icon) != FALSE, "fixture shell-loss simulation");
    SendMessageW(tray, RegisterWindowMessageW(L"TaskbarCreated"), 0, 0);
    check(Shell_NotifyIconW(NIM_DELETE, &own_icon) != FALSE,
          "TaskbarCreated restores the fixture notification icon");
  }
  GHOST_TrayWin32_Remove();
  check(!GHOST_TrayWin32_IsActive(), "fixture tray icon removed");
  SelectObject(paint, previous);
  DeleteObject(bitmap);
  DeleteDC(paint);
  ReleaseDC(window, owner_dc);
  DestroyWindow(window);
  puts(failures ? "check_native_theme: FAILED" : "check_native_theme: PASS");
  return failures ? 1 : 0;
}
