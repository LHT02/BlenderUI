/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright 2001-2002 NaN Holding BV. All rights reserved. */

/** \file
 * \ingroup GHOST
 */

#include "GHOST_WindowWin32.hh"
#include "GHOST_ContextD3D.hh"
#include "GHOST_ContextNone.hh"
#include "GHOST_DropTargetWin32.hh"
#include "GHOST_SystemWin32.hh"
#include "GHOST_ThemeWin32.hh"
#include "GHOST_WindowManager.hh"
#include "utf_winfunc.h"
#include "utfconv.h"

#include "GHOST_ContextWGL.hh"
#ifdef WITH_VULKAN_BACKEND
#  include "GHOST_ContextVK.hh"
#endif

#include <Dwmapi.h>

#include <assert.h>
#include <atomic>
#include <cstdint>
#include <math.h>
#include <shellscalingapi.h>
#include <shellapi.h>
#include <string.h>
#include <windowsx.h>

#ifndef GET_POINTERID_WPARAM
#  define GET_POINTERID_WPARAM(wParam) (LOWORD(wParam))
#endif /* GET_POINTERID_WPARAM */

const wchar_t *GHOST_WindowWin32::s_windowClassName = L"GHOST_WindowClass";
const int GHOST_WindowWin32::s_maxTitleLength = 128;

/* force NVidia Optimus to used dedicated graphics */
extern "C" {
__declspec(dllexport) DWORD NvOptimusEnablement = 0x00000001;
}

GHOST_WindowWin32::GHOST_WindowWin32(GHOST_SystemWin32 *system,
                                     const char *title,
                                     int32_t left,
                                     int32_t top,
                                     uint32_t width,
                                     uint32_t height,
                                     GHOST_TWindowState state,
                                     GHOST_TDrawingContextType type,
                                     bool wantStereoVisual,
                                     bool alphaBackground,
                                     GHOST_WindowWin32 *parentwindow,
                                     bool is_debug,
                                     bool dialog,
                                     bool shell_window,
                                     bool taskbar_window,
                                     bool desktop_window,
                                     bool passive_window)
    : GHOST_Window(width, height, state, wantStereoVisual, false),
      m_mousePresent(false),
      m_inLiveResize(false),
      m_system(system),
      m_dropTarget(NULL),
      m_hWnd(0),
      m_bluiAppBarPreviousProc(nullptr),
      m_bluiAppBarNotifying(false),
      m_bluiDesktopWindow(desktop_window),
      m_bluiDesktopReady(false),
      m_bluiDesktopCleanupHwnd(nullptr),
      m_bluiDesktopCleanupDC(nullptr),
      m_hDC(0),
      m_isDialog(dialog),
      m_hasMouseCaptured(false),
      m_hasGrabMouse(false),
      m_nPressedButtons(0),
      m_customCursor(0),
      m_wantAlphaBackground(alphaBackground),
      m_Bar(NULL),
      m_wintab(NULL),
      m_lastPointerTabletData(GHOST_TABLET_DATA_NONE),
      m_normal_state(GHOST_kWindowStateNormal),
      m_user32(::LoadLibrary("user32.dll")),
      m_parentWindowHwnd(parentwindow ? parentwindow->m_hWnd : HWND_DESKTOP),
      m_directManipulationHelper(NULL),
      m_debug_context(is_debug)
{
  /* Desktop loss must retain the exact GL context for context-local GPU cleanup.
   * Other backends need an equivalent surface-loss contract before opting in. */
  if (desktop_window && type != GHOST_kDrawingContextTypeOpenGL) {
    return;
  }
  DWORD style = parentwindow ?
                    WS_POPUPWINDOW | WS_CAPTION | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SIZEBOX :
                    WS_OVERLAPPEDWINDOW;
  if (shell_window) {
    style = WS_POPUP | WS_CLIPSIBLINGS | WS_CLIPCHILDREN;
  }

  if (state == GHOST_kWindowStateFullScreen) {
    style |= WS_MAXIMIZE;
  }

  /* Forces owned windows onto taskbar and allows minimization. */
  DWORD extended_style = parentwindow ? WS_EX_APPWINDOW : 0;
  if (shell_window) {
    extended_style = WS_EX_TOOLWINDOW;
    if (taskbar_window || passive_window) {
      extended_style |= WS_EX_NOACTIVATE;
    }
  }

  if (dialog) {
    /* When we are ready to make windows of this type:
     * style = WS_POPUPWINDOW | WS_CAPTION
     * extended_style = WS_EX_DLGMODALFRAME | WS_EX_TOPMOST
     */
  }

  RECT win_rect = {left, top, long(left + width), long(top + height)};
  adjustWindowRectForClosestMonitor(&win_rect, style, extended_style);

  wchar_t *title_16 = alloc_utf16_from_8((char *)title, 0);
  m_hWnd = ::CreateWindowExW(extended_style,                 /* window extended style */
                             desktop_window ? L"BLUI_DesktopWindowClass" : s_windowClassName,
                             title_16,                       /* pointer to window name */
                             style,                          /* window style */
                             win_rect.left,                  /* horizontal position of window */
                             win_rect.top,                   /* vertical position of window */
                             win_rect.right - win_rect.left, /* window width */
                             win_rect.bottom - win_rect.top, /* window height */
                             m_parentWindowHwnd,             /* handle to parent or owner window */
                             0,                    /* handle to menu or child-window identifier */
                             ::GetModuleHandle(0), /* handle to application instance */
                             0);                   /* pointer to window-creation data */
  free(title_16);

  if (m_hWnd == NULL) {
    return;
  }

  /*  Store the device context. */
  m_hDC = ::GetDC(m_hWnd);

  if (!setDrawingContextType(type)) {
    const char *title = "Blender - Unsupported Graphics Card Configuration";
    const char *text =
        "A graphics card and driver with support for OpenGL 3.3 or higher is "
        "required.\n\nInstalling the latest driver for your graphics card might resolve the "
        "issue.";
    if (GetSystemMetrics(SM_CMONITORS) > 1) {
      text =
          "A graphics card and driver with support for OpenGL 3.3 or higher is "
          "required.\n\nPlugging all monitors into your primary graphics card might resolve "
          "this issue. Installing the latest driver for your graphics card could also help.";
    }
    MessageBox(m_hWnd, text, title, MB_OK | MB_ICONERROR);
    ::ReleaseDC(m_hWnd, m_hDC);
    ::DestroyWindow(m_hWnd);
    m_hWnd = NULL;
    if (!parentwindow && !shell_window) {
      exit(0);
    }
    return;
  }

  if (desktop_window && !createBluiDesktopCleanupSurface()) {
    return;  /* Fail closed; never host a canvas whose GPU cleanup cannot survive parent loss. */
  }

  RegisterTouchWindow(m_hWnd, 0);

  /* Register as drop-target. #OleInitialize(0) required first, done in GHOST_SystemWin32. */
  m_dropTarget = new GHOST_DropTargetWin32(this, m_system);
  ::RegisterDragDrop(m_hWnd, m_dropTarget);

  /* Store a pointer to this class in the window structure. */
  ::SetWindowLongPtr(m_hWnd, GWLP_USERDATA, (LONG_PTR)this);
  if (desktop_window) {
    static std::atomic<uintptr_t> next_instance{0};
    uintptr_t instance = next_instance.fetch_add(1, std::memory_order_relaxed) + 1;
    if (!instance) {
      instance = next_instance.fetch_add(1, std::memory_order_relaxed) + 1;
    }
    if (!::SetPropW(m_hWnd, L"BLUI.DesktopInstance.v1", reinterpret_cast<HANDLE>(instance)) ||
        !::SetPropW(m_hWnd, L"BLUI.DesktopHost.v1", reinterpret_cast<HANDLE>(1))) {
      return;
    }
    m_bluiDesktopReady = true;
  }
  if (taskbar_window) {
    m_bluiAppBarPreviousProc = reinterpret_cast<WNDPROC>(::SetWindowLongPtrW(
        m_hWnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(bluiAppBarWndProc)));
  }

  if (!m_system->m_windowFocus) {
    /* If we don't want focus then lower to bottom. */
    ::SetWindowPos(m_hWnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
  }

  if (parentwindow) {
    /* Release any parent capture to allow immediate interaction (#90110). */
    ::ReleaseCapture();
    parentwindow->lostMouseCapture();
  }

  /* Show the window. */
  int nCmdShow;
  switch (state) {
    case GHOST_kWindowStateMaximized:
      nCmdShow = SW_SHOWMAXIMIZED;
      break;
    case GHOST_kWindowStateMinimized:
      nCmdShow = (m_system->m_windowFocus) ? SW_SHOWMINIMIZED : SW_SHOWMINNOACTIVE;
      break;
    case GHOST_kWindowStateNormal:
    default:
      nCmdShow = (m_system->m_windowFocus) ? SW_SHOWNORMAL : SW_SHOWNOACTIVATE;
      break;
  }

  ThemeRefresh();
  if (taskbar_window || passive_window) {
    nCmdShow = SW_SHOWNOACTIVATE;
  }
  if (desktop_window) {
    nCmdShow = SW_HIDE;  /* Host helper explicitly shows only after verified attachment. */
  }

  ::ShowWindow(m_hWnd, nCmdShow);

#ifdef WIN32_COMPOSITING
  if (alphaBackground && parentwindowhwnd == 0) {

    HRESULT hr = S_OK;

    /* Create and populate the Blur Behind structure. */
    DWM_BLURBEHIND bb = {0};

    /* Enable Blur Behind and apply to the entire client area. */
    bb.dwFlags = DWM_BB_ENABLE | DWM_BB_BLURREGION;
    bb.fEnable = true;
    bb.hRgnBlur = CreateRectRgn(0, 0, -1, -1);

    /* Apply Blur Behind. */
    hr = DwmEnableBlurBehindWindow(m_hWnd, &bb);
    DeleteObject(bb.hRgnBlur);
  }
#endif

  /* Force an initial paint of the window. */
  ::UpdateWindow(m_hWnd);

  /* Initialize WINTAB. */
  if (system->getTabletAPI() != GHOST_kTabletWinPointer) {
    loadWintab(GHOST_kWindowStateMinimized != state);
  }

  /* Desktop children have no taskbar button/progress. Keep Explorer progress
   * COM entirely out of their creation and teardown; normal windows retain it. */
  if (!m_bluiDesktopWindow) {
    CoCreateInstance(
        CLSID_TaskbarList, NULL, CLSCTX_INPROC_SERVER, IID_ITaskbarList3, (LPVOID *)&m_Bar);
  }

  /* Initialize Direct Manipulation. */
  m_directManipulationHelper = GHOST_DirectManipulationHelper::create(m_hWnd, getDPIHint());
}

void GHOST_WindowWin32::updateDirectManipulation()
{
  if (!m_directManipulationHelper) {
    return;
  }

  m_directManipulationHelper->update();
}

void GHOST_WindowWin32::onPointerHitTest(WPARAM wParam)
{
  /* Only #DM_POINTERHITTEST can be the first message of input sequence of touch-pad input. */

  if (!m_directManipulationHelper) {
    return;
  }

  UINT32 pointerId = GET_POINTERID_WPARAM(wParam);
  POINTER_INPUT_TYPE pointerType;
  if (GetPointerType(pointerId, &pointerType) && pointerType == PT_TOUCHPAD) {
    m_directManipulationHelper->onPointerHitTest(pointerId);
  }
}

GHOST_TTrackpadInfo GHOST_WindowWin32::getTrackpadInfo()
{
  if (!m_directManipulationHelper) {
    return {0, 0, 0};
  }

  return m_directManipulationHelper->getTrackpadInfo();
}

GHOST_WindowWin32::~GHOST_WindowWin32()
{
  if (m_Bar) {
    if (m_hWnd) {
      m_Bar->SetProgressState(m_hWnd, TBPF_NOPROGRESS);
    }
    m_Bar->Release();
    m_Bar = NULL;
  }

  closeWintab();

  if (m_user32) {
    FreeLibrary(m_user32);
    m_user32 = NULL;
  }

  if (m_customCursor) {
    DestroyCursor(m_customCursor);
    m_customCursor = NULL;
  }

  if (m_hWnd != NULL && m_hDC != NULL && releaseNativeHandles()) {
    ::ReleaseDC(m_hWnd, m_hDC);
    m_hDC = NULL;
  }

  if (m_hWnd) {
    releaseBluiAppBar();
    if (m_bluiAppBarPreviousProc && ::IsWindow(m_hWnd)) {
      ::SetWindowLongPtrW(
          m_hWnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(m_bluiAppBarPreviousProc));
      m_bluiAppBarPreviousProc = nullptr;
    }
    /* If this window is referenced by others as parent, clear that relation or windows will free
     * the handle while we still reference it. */
    for (GHOST_IWindow *iter_win : m_system->getWindowManager()->getWindows()) {
      GHOST_WindowWin32 *iter_winwin = (GHOST_WindowWin32 *)iter_win;
      if (iter_winwin->m_parentWindowHwnd == m_hWnd) {
        ::SetWindowLongPtr(iter_winwin->m_hWnd, GWLP_HWNDPARENT, NULL);
        iter_winwin->m_parentWindowHwnd = 0;
      }
    }

    releaseDropTarget();
    ::RemovePropW(m_hWnd, L"BLUI.DesktopHost.v1");
    ::RemovePropW(m_hWnd, L"BLUI.DesktopInstance.v1");
    ::SetWindowLongPtr(m_hWnd, GWLP_USERDATA, NULL);
    ::DestroyWindow(m_hWnd);
    m_hWnd = 0;
  }

  releaseDropTarget();  /* Also release our COM reference after unexpected native destruction. */
  releaseBluiDesktopCleanupSurface();

  delete m_directManipulationHelper;
  m_directManipulationHelper = NULL;
}

namespace {
constexpr UINT blui_appbar_callback = WM_APP + 0x2A7;
const wchar_t *blui_appbar_owner = L"BLUI.AppBar.Registered";
const wchar_t *blui_appbar_token = L"BLUI.AppBar.Token";
const wchar_t *blui_appbar_generation = L"BLUI.AppBar.Generation";
const wchar_t *blui_appbar_restart = L"BLUI.AppBar.Restart";
const wchar_t *blui_appbar_fullscreen = L"BLUI.AppBar.Fullscreen";

bool blui_appbar_owned(HWND hwnd)
{
  DWORD pid = 0;
  return reinterpret_cast<ULONG_PTR>(::GetPropW(hwnd, blui_appbar_owner)) ==
             ::GetCurrentProcessId() &&
         ::GetWindowThreadProcessId(hwnd, &pid) == ::GetCurrentThreadId() &&
         pid == ::GetCurrentProcessId() &&
         !(::GetWindowLongPtrW(hwnd, GWL_STYLE) & WS_CHILD) &&
         (::GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_NOACTIVATE);
}

void blui_appbar_bump(HWND hwnd, const wchar_t *name)
{
  ULONG_PTR value = reinterpret_cast<ULONG_PTR>(::GetPropW(hwnd, name)) + 1;
  ::SetPropW(hwnd, name, reinterpret_cast<HANDLE>(value ? value : 1));
}
}  // namespace

LRESULT CALLBACK GHOST_WindowWin32::bluiAppBarWndProc(HWND hwnd,
                                                   UINT message,
                                                   WPARAM wparam,
                                                   LPARAM lparam)
{
  GHOST_WindowWin32 *window = reinterpret_cast<GHOST_WindowWin32 *>(
      ::GetWindowLongPtrW(hwnd, GWLP_USERDATA));
  if (!window || window->m_hWnd != hwnd || !window->m_bluiAppBarPreviousProc) {
    return ::DefWindowProcW(hwnd, message, wparam, lparam);
  }
  if (window->handleBluiAppBarMessage(message, wparam, lparam)) {
    return 0;
  }
  return ::CallWindowProcW(window->m_bluiAppBarPreviousProc, hwnd, message, wparam, lparam);
}

bool GHOST_WindowWin32::handleBluiAppBarMessage(UINT message, WPARAM wparam, LPARAM lparam)
{
  if (!blui_appbar_owned(m_hWnd)) {
    return false;
  }
  static const UINT taskbar_created = ::RegisterWindowMessageW(L"TaskbarCreated");
  if (taskbar_created && message == taskbar_created) {
    blui_appbar_bump(m_hWnd, blui_appbar_restart);
    blui_appbar_bump(m_hWnd, blui_appbar_generation);
    return true;
  }
  if (message == blui_appbar_callback) {
    if (wparam == ABN_POSCHANGED || wparam == ABN_STATECHANGE) {
      /* Timer reads the generation. Never synchronously QUERY/SETPOS from WndProc. */
      blui_appbar_bump(m_hWnd, blui_appbar_generation);
    }
    else if (wparam == ABN_FULLSCREENAPP) {
      if (lparam) {
        ::SetPropW(m_hWnd, blui_appbar_fullscreen, reinterpret_cast<HANDLE>(1));
      }
      else {
        ::RemovePropW(m_hWnd, blui_appbar_fullscreen);
      }
      const bool was_notifying = m_bluiAppBarNotifying;
      m_bluiAppBarNotifying = true;
      ::SetWindowPos(m_hWnd,
                     lparam ? HWND_BOTTOM : HWND_TOPMOST,
                     0,
                     0,
                     0,
                     0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
      m_bluiAppBarNotifying = was_notifying;
    }
    return true;
  }
  if (message == WM_NCDESTROY) {
    releaseBluiAppBar();
    return false;
  }
  if (!m_bluiAppBarNotifying && (message == WM_WINDOWPOSCHANGED || message == WM_ACTIVATE)) {
    APPBARDATA data = {};
    data.cbSize = sizeof(data);
    data.hWnd = m_hWnd;
    data.lParam = message == WM_ACTIVATE && LOWORD(wparam) != WA_INACTIVE;
    m_bluiAppBarNotifying = true;
    ::SHAppBarMessage(message == WM_ACTIVATE ? ABM_ACTIVATE : ABM_WINDOWPOSCHANGED, &data);
    m_bluiAppBarNotifying = false;
  }
  return false;
}

void GHOST_WindowWin32::releaseBluiAppBar()
{
  if (!m_hWnd || !blui_appbar_owned(m_hWnd)) {
    return;
  }
  /* Clear the marker first, so synchronous Shell notifications cannot re-enter. */
  ::RemovePropW(m_hWnd, blui_appbar_owner);
  ::RemovePropW(m_hWnd, blui_appbar_token);
  ::RemovePropW(m_hWnd, blui_appbar_generation);
  ::RemovePropW(m_hWnd, blui_appbar_restart);
  ::RemovePropW(m_hWnd, blui_appbar_fullscreen);
  APPBARDATA data = {};
  data.cbSize = sizeof(data);
  data.hWnd = m_hWnd;
  ::SHAppBarMessage(ABM_REMOVE, &data);
}

void GHOST_WindowWin32::adjustWindowRectForClosestMonitor(LPRECT win_rect,
                                                          DWORD dwStyle,
                                                          DWORD dwExStyle)
{
  /* Get Details of the closest monitor. */
  HMONITOR hmonitor = MonitorFromRect(win_rect, MONITOR_DEFAULTTONEAREST);
  MONITORINFOEX monitor;
  monitor.cbSize = sizeof(MONITORINFOEX);
  monitor.dwFlags = 0;
  GetMonitorInfo(hmonitor, &monitor);

  /* Constrain requested size and position to fit within this monitor. */
  LONG width = min(monitor.rcWork.right - monitor.rcWork.left, win_rect->right - win_rect->left);
  LONG height = min(monitor.rcWork.bottom - monitor.rcWork.top, win_rect->bottom - win_rect->top);
  win_rect->left = min(max(monitor.rcWork.left, win_rect->left), monitor.rcWork.right - width);
  win_rect->right = win_rect->left + width;
  win_rect->top = min(max(monitor.rcWork.top, win_rect->top), monitor.rcWork.bottom - height);
  win_rect->bottom = win_rect->top + height;

  /* With Windows 10 and newer we can adjust for chrome that differs with DPI and scale. */
  GHOST_WIN32_AdjustWindowRectExForDpi fpAdjustWindowRectExForDpi = nullptr;
  if (m_user32) {
    fpAdjustWindowRectExForDpi = (GHOST_WIN32_AdjustWindowRectExForDpi)::GetProcAddress(
        m_user32, "AdjustWindowRectExForDpi");
  }

  /* Adjust to allow for caption, borders, shadows, scaling, etc. Resulting values can be
   * correctly outside of monitor bounds. NOTE: You cannot specify #WS_OVERLAPPED when calling. */
  if (fpAdjustWindowRectExForDpi) {
    UINT dpiX, dpiY;
    GetDpiForMonitor(hmonitor, MDT_EFFECTIVE_DPI, &dpiX, &dpiY);
    fpAdjustWindowRectExForDpi(win_rect, dwStyle & ~WS_OVERLAPPED, FALSE, dwExStyle, dpiX);
  }
  else {
    AdjustWindowRectEx(win_rect, dwStyle & ~WS_OVERLAPPED, FALSE, dwExStyle);
  }

  /* But never allow a top position that can hide part of the title bar. */
  win_rect->top = max(monitor.rcWork.top, win_rect->top);
}

bool GHOST_WindowWin32::getValid() const
{
  return GHOST_Window::getValid() && m_hWnd != 0 && m_hDC != 0 &&
         (!m_bluiDesktopWindow || m_bluiDesktopReady);
}

bool GHOST_WindowWin32::createBluiDesktopCleanupSurface()
{
  RECT rect = {};
  ::GetWindowRect(m_hWnd, &rect);
  m_bluiDesktopCleanupHwnd = ::CreateWindowExW(WS_EX_TOOLWINDOW,
                                             L"STATIC",
                                             L"BLUI Desktop GPU Cleanup",
                                             WS_POPUP,
                                             rect.left,
                                             rect.top,
                                             1,
                                             1,
                                             nullptr,
                                             nullptr,
                                             ::GetModuleHandleW(nullptr),
                                             nullptr);
  if (!m_bluiDesktopCleanupHwnd) {
    return false;
  }
  m_bluiDesktopCleanupDC = ::GetDC(m_bluiDesktopCleanupHwnd);
  const int format = ::GetPixelFormat(m_hDC);
  PIXELFORMATDESCRIPTOR descriptor = {};
  return m_bluiDesktopCleanupDC && format &&
         ::DescribePixelFormat(m_hDC, format, sizeof(descriptor), &descriptor) &&
         ::SetPixelFormat(m_bluiDesktopCleanupDC, format, &descriptor);
}

void GHOST_WindowWin32::releaseBluiDesktopCleanupSurface()
{
  if (m_bluiDesktopCleanupDC) {
    /* Only after queued WM GPU cleanup: detach the context from its parking DC. */
    releaseNativeHandles();
    ::ReleaseDC(m_bluiDesktopCleanupHwnd, m_bluiDesktopCleanupDC);
    m_bluiDesktopCleanupDC = nullptr;
  }
  if (m_bluiDesktopCleanupHwnd) {
    ::DestroyWindow(m_bluiDesktopCleanupHwnd);
    m_bluiDesktopCleanupHwnd = nullptr;
  }
}

void GHOST_WindowWin32::releaseDropTarget()
{
  if (m_dropTarget) {
    if (m_hWnd) {
      ::RevokeDragDrop(m_hWnd);
    }
    m_dropTarget->Release();
    m_dropTarget = nullptr;
  }
}

void GHOST_WindowWin32::invalidateBluiDesktopHandle()
{
  /* Keep the C++/GPU objects alive until the queued window-close event cancels
   * native handlers and removes RNA. Never free them from WM_NCDESTROY. */
  if (m_bluiDesktopWindow && m_hWnd) {
    /* Rebind this exact HGLRC, not another normal window's GL context: VAO/FBO
     * names are context-local. The private 1px surface is never shown or parented. */
    static_cast<GHOST_ContextWGL *>(getContext())->setBluiDesktopCleanupHandles(
        m_bluiDesktopCleanupHwnd, m_bluiDesktopCleanupDC);
    releaseDropTarget();
    closeWintab();
    delete m_directManipulationHelper;
    m_directManipulationHelper = nullptr;
    ::ReleaseDC(m_hWnd, m_hDC);
    m_hDC = nullptr;
    m_hWnd = nullptr;
    m_bluiDesktopReady = false;
  }
}

GHOST_TSuccess GHOST_WindowWin32::swapBuffers()
{
  return m_bluiDesktopWindow && !getValid() ? GHOST_kFailure : GHOST_Window::swapBuffers();
}

GHOST_TSuccess GHOST_WindowWin32::activateDrawingContext()
{
  return m_bluiDesktopWindow && !getValid() ? GHOST_kFailure :
                                            GHOST_Window::activateDrawingContext();
}

HWND GHOST_WindowWin32::getHWND() const
{
  return m_hWnd;
}

void GHOST_WindowWin32::setTitle(const char *title)
{
  wchar_t *title_16 = alloc_utf16_from_8((char *)title, 0);
  ::SetWindowTextW(m_hWnd, (wchar_t *)title_16);
  free(title_16);
}

std::string GHOST_WindowWin32::getTitle() const
{
  std::wstring wtitle(::GetWindowTextLengthW(m_hWnd) + 1, L'\0');
  ::GetWindowTextW(m_hWnd, &wtitle[0], wtitle.capacity());

  std::string title(count_utf_8_from_16(wtitle.c_str()) + 1, '\0');
  conv_utf_16_to_8(wtitle.c_str(), &title[0], title.capacity());

  return title;
}

void GHOST_WindowWin32::getWindowBounds(GHOST_Rect &bounds) const
{
  RECT rect = {};
  ::GetWindowRect(m_hWnd, &rect);
  bounds.m_b = rect.bottom;
  bounds.m_l = rect.left;
  bounds.m_r = rect.right;
  bounds.m_t = rect.top;
}

void GHOST_WindowWin32::getClientBounds(GHOST_Rect &bounds) const
{
  RECT rect = {};
  POINT coord;
  if (m_hWnd && !IsIconic(m_hWnd)) {
    ::GetClientRect(m_hWnd, &rect);

    coord.x = rect.left;
    coord.y = rect.top;
    ::ClientToScreen(m_hWnd, &coord);

    bounds.m_l = coord.x;
    bounds.m_t = coord.y;

    coord.x = rect.right;
    coord.y = rect.bottom;
    ::ClientToScreen(m_hWnd, &coord);

    bounds.m_r = coord.x;
    bounds.m_b = coord.y;
  }
  else {
    bounds.m_b = 0;
    bounds.m_l = 0;
    bounds.m_r = 0;
    bounds.m_t = 0;
  }
}

GHOST_TSuccess GHOST_WindowWin32::setClientWidth(uint32_t width)
{
  if (!m_hWnd) {
    return GHOST_kFailure;
  }
  GHOST_TSuccess success;
  GHOST_Rect cBnds, wBnds;
  getClientBounds(cBnds);
  if (cBnds.getWidth() != (int32_t)width) {
    getWindowBounds(wBnds);
    int cx = wBnds.getWidth() + width - cBnds.getWidth();
    int cy = wBnds.getHeight();
    success = ::SetWindowPos(m_hWnd, HWND_TOP, 0, 0, cx, cy, SWP_NOMOVE | SWP_NOZORDER) ?
                  GHOST_kSuccess :
                  GHOST_kFailure;
  }
  else {
    success = GHOST_kSuccess;
  }
  return success;
}

GHOST_TSuccess GHOST_WindowWin32::setClientHeight(uint32_t height)
{
  if (!m_hWnd) {
    return GHOST_kFailure;
  }
  GHOST_TSuccess success;
  GHOST_Rect cBnds, wBnds;
  getClientBounds(cBnds);
  if (cBnds.getHeight() != (int32_t)height) {
    getWindowBounds(wBnds);
    int cx = wBnds.getWidth();
    int cy = wBnds.getHeight() + height - cBnds.getHeight();
    success = ::SetWindowPos(m_hWnd, HWND_TOP, 0, 0, cx, cy, SWP_NOMOVE | SWP_NOZORDER) ?
                  GHOST_kSuccess :
                  GHOST_kFailure;
  }
  else {
    success = GHOST_kSuccess;
  }
  return success;
}

GHOST_TSuccess GHOST_WindowWin32::setClientSize(uint32_t width, uint32_t height)
{
  if (!m_hWnd) {
    return GHOST_kFailure;
  }
  GHOST_TSuccess success;
  GHOST_Rect cBnds, wBnds;
  getClientBounds(cBnds);
  if ((cBnds.getWidth() != (int32_t)width) || (cBnds.getHeight() != (int32_t)height)) {
    getWindowBounds(wBnds);
    int cx = wBnds.getWidth() + width - cBnds.getWidth();
    int cy = wBnds.getHeight() + height - cBnds.getHeight();
    success = ::SetWindowPos(m_hWnd, HWND_TOP, 0, 0, cx, cy, SWP_NOMOVE | SWP_NOZORDER) ?
                  GHOST_kSuccess :
                  GHOST_kFailure;
  }
  else {
    success = GHOST_kSuccess;
  }
  return success;
}

GHOST_TWindowState GHOST_WindowWin32::getState() const
{
  if (::IsIconic(m_hWnd)) {
    return GHOST_kWindowStateMinimized;
  }
  else if (::IsZoomed(m_hWnd)) {
    LONG_PTR result = ::GetWindowLongPtr(m_hWnd, GWL_STYLE);
    return (result & WS_CAPTION) ? GHOST_kWindowStateMaximized : GHOST_kWindowStateFullScreen;
  }
  return GHOST_kWindowStateNormal;
}

void GHOST_WindowWin32::screenToClient(int32_t inX,
                                       int32_t inY,
                                       int32_t &outX,
                                       int32_t &outY) const
{
  POINT point = {inX, inY};
  ::ScreenToClient(m_hWnd, &point);
  outX = point.x;
  outY = point.y;
}

void GHOST_WindowWin32::clientToScreen(int32_t inX,
                                       int32_t inY,
                                       int32_t &outX,
                                       int32_t &outY) const
{
  POINT point = {inX, inY};
  ::ClientToScreen(m_hWnd, &point);
  outX = point.x;
  outY = point.y;
}

GHOST_TSuccess GHOST_WindowWin32::setState(GHOST_TWindowState state)
{
  if (!m_hWnd) {
    return GHOST_kFailure;
  }
  GHOST_TWindowState curstate = getState();
  LONG_PTR style = GetWindowLongPtr(m_hWnd, GWL_STYLE) | WS_CAPTION;
  WINDOWPLACEMENT wp;
  wp.length = sizeof(WINDOWPLACEMENT);
  ::GetWindowPlacement(m_hWnd, &wp);

  switch (state) {
    case GHOST_kWindowStateMinimized:
      wp.showCmd = SW_MINIMIZE;
      break;
    case GHOST_kWindowStateMaximized:
      wp.showCmd = SW_SHOWMAXIMIZED;
      break;
    case GHOST_kWindowStateFullScreen:
      if (curstate != state && curstate != GHOST_kWindowStateMinimized) {
        m_normal_state = curstate;
      }
      wp.showCmd = SW_SHOWMAXIMIZED;
      wp.ptMaxPosition.x = 0;
      wp.ptMaxPosition.y = 0;
      style &= ~(WS_CAPTION | WS_MAXIMIZE);
      break;
    case GHOST_kWindowStateNormal:
    default:
      if (curstate == GHOST_kWindowStateFullScreen &&
          m_normal_state == GHOST_kWindowStateMaximized) {
        wp.showCmd = SW_SHOWMAXIMIZED;
        m_normal_state = GHOST_kWindowStateNormal;
      }
      else {
        wp.showCmd = SW_SHOWNORMAL;
      }
      break;
  }
  ::SetWindowLongPtr(m_hWnd, GWL_STYLE, style);
  /* #SetWindowLongPtr Docs:
   * Frame changes not visible until #SetWindowPos with #SWP_FRAMECHANGED. */
  ::SetWindowPos(m_hWnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED);
  return ::SetWindowPlacement(m_hWnd, &wp) == TRUE ? GHOST_kSuccess : GHOST_kFailure;
}

GHOST_TSuccess GHOST_WindowWin32::setOrder(GHOST_TWindowOrder order)
{
  if (!m_hWnd) {
    return GHOST_kFailure;
  }
  HWND hWndInsertAfter, hWndToRaise;

  if (order == GHOST_kWindowOrderBottom) {
    hWndInsertAfter = HWND_BOTTOM;
    hWndToRaise = ::GetWindow(m_hWnd, GW_HWNDNEXT); /* the window to raise */
  }
  else {
    if (getState() == GHOST_kWindowStateMinimized) {
      setState(GHOST_kWindowStateNormal);
    }
    hWndInsertAfter = HWND_TOP;
    hWndToRaise = NULL;
  }

  if (::SetWindowPos(m_hWnd, hWndInsertAfter, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE) == FALSE) {
    return GHOST_kFailure;
  }

  if (hWndToRaise &&
      ::SetWindowPos(hWndToRaise, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE) == FALSE)
  {
    return GHOST_kFailure;
  }
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_WindowWin32::invalidate()
{
  GHOST_TSuccess success;
  if (m_hWnd) {
    success = ::InvalidateRect(m_hWnd, 0, FALSE) != 0 ? GHOST_kSuccess : GHOST_kFailure;
  }
  else {
    success = GHOST_kFailure;
  }
  return success;
}

GHOST_Context *GHOST_WindowWin32::newDrawingContext(GHOST_TDrawingContextType type)
{
  if (type == GHOST_kDrawingContextTypeOpenGL) {
    GHOST_Context *context;

    /* - AMD and Intel give us exactly this version
     * - NVIDIA gives at least this version <-- desired behavior
     * So we ask for 4.5, 4.4 ... 3.3 in descending order
     * to get the best version on the user's system. */
    for (int minor = 5; minor >= 0; --minor) {
      context = new GHOST_ContextWGL(m_wantStereoVisual,
                                     m_wantAlphaBackground,
                                     m_hWnd,
                                     m_hDC,
                                     WGL_CONTEXT_CORE_PROFILE_BIT_ARB,
                                     4,
                                     minor,
                                     (m_debug_context ? WGL_CONTEXT_DEBUG_BIT_ARB : 0),
                                     GHOST_OPENGL_WGL_RESET_NOTIFICATION_STRATEGY);

      if (context->initializeDrawingContext()) {
        return context;
      }
      else {
        delete context;
      }
    }
    context = new GHOST_ContextWGL(m_wantStereoVisual,
                                   m_wantAlphaBackground,
                                   m_hWnd,
                                   m_hDC,
                                   WGL_CONTEXT_CORE_PROFILE_BIT_ARB,
                                   3,
                                   3,
                                   (m_debug_context ? WGL_CONTEXT_DEBUG_BIT_ARB : 0),
                                   GHOST_OPENGL_WGL_RESET_NOTIFICATION_STRATEGY);

    if (context && !context->initializeDrawingContext()) {
      delete context;
      context = nullptr;
    }

    return context;
  }
  else if (type == GHOST_kDrawingContextTypeD3D) {
    GHOST_Context *context;

    context = new GHOST_ContextD3D(false, m_hWnd);
    if (!context->initializeDrawingContext()) {
      delete context;
      context = nullptr;
    }

    return context;
  }

#ifdef WITH_VULKAN_BACKEND
  else if (type == GHOST_kDrawingContextTypeVulkan) {
    GHOST_Context *context = new GHOST_ContextVK(false, m_hWnd, 1, 2, m_debug_context);

    if (context->initializeDrawingContext()) {
      return context;
    }
    else {
      delete context;
    }
  }
#endif

  return NULL;
}

void GHOST_WindowWin32::lostMouseCapture()
{
  if (m_hasMouseCaptured) {
    m_hasGrabMouse = false;
    m_nPressedButtons = 0;
    m_hasMouseCaptured = false;
  }
}

bool GHOST_WindowWin32::isDialog() const
{
  return m_isDialog;
}

void GHOST_WindowWin32::updateMouseCapture(GHOST_MouseCaptureEventWin32 event)
{
  if (!m_hWnd) {
    return;
  }
  switch (event) {
    case MousePressed:
      m_nPressedButtons++;
      break;
    case MouseReleased:
      if (m_nPressedButtons)
        m_nPressedButtons--;
      break;
    case OperatorGrab:
      m_hasGrabMouse = true;
      break;
    case OperatorUngrab:
      m_hasGrabMouse = false;
      break;
  }

  if (!m_nPressedButtons && !m_hasGrabMouse && m_hasMouseCaptured) {
    ::ReleaseCapture();
    m_hasMouseCaptured = false;
  }
  else if ((m_nPressedButtons || m_hasGrabMouse) && !m_hasMouseCaptured) {
    ::SetCapture(m_hWnd);
    m_hasMouseCaptured = true;
  }
}

HCURSOR GHOST_WindowWin32::getStandardCursor(GHOST_TStandardCursor shape) const
{
  /* Convert GHOST cursor to Windows OEM cursor. */
  HANDLE cursor = NULL;
  HMODULE module = ::GetModuleHandle(0);
  uint32_t flags = LR_SHARED | LR_DEFAULTSIZE;
  int cx = 0, cy = 0;

  switch (shape) {
    case GHOST_kStandardCursorCustom:
      if (m_customCursor) {
        return m_customCursor;
      }
      else {
        return NULL;
      }
    case GHOST_kStandardCursorRightArrow:
      cursor = ::LoadImage(module, "arrowright_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorLeftArrow:
      cursor = ::LoadImage(module, "arrowleft_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorUpArrow:
      cursor = ::LoadImage(module, "arrowup_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorDownArrow:
      cursor = ::LoadImage(module, "arrowdown_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorVerticalSplit:
      cursor = ::LoadImage(module, "splitv_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorHorizontalSplit:
      cursor = ::LoadImage(module, "splith_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorKnife:
      cursor = ::LoadImage(module, "knife_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorEyedropper:
      cursor = ::LoadImage(module, "eyedropper_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorZoomIn:
      cursor = ::LoadImage(module, "zoomin_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorZoomOut:
      cursor = ::LoadImage(module, "zoomout_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorMove:
      cursor = ::LoadImage(module, "handopen_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorNSEWScroll:
      cursor = ::LoadImage(module, "scrollnsew_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorNSScroll:
      cursor = ::LoadImage(module, "scrollns_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorEWScroll:
      cursor = ::LoadImage(module, "scrollew_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorHelp:
      cursor = ::LoadImage(NULL, IDC_HELP, IMAGE_CURSOR, cx, cy, flags);
      break; /* Arrow and question mark */
    case GHOST_kStandardCursorWait:
      cursor = ::LoadImage(NULL, IDC_WAIT, IMAGE_CURSOR, cx, cy, flags);
      break; /* Hourglass */
    case GHOST_kStandardCursorText:
      cursor = ::LoadImage(NULL, IDC_IBEAM, IMAGE_CURSOR, cx, cy, flags);
      break; /* I-beam */
    case GHOST_kStandardCursorCrosshair:
      cursor = ::LoadImage(module, "cross_cursor", IMAGE_CURSOR, cx, cy, flags);
      break; /* Standard Cross */
    case GHOST_kStandardCursorCrosshairA:
      cursor = ::LoadImage(module, "crossA_cursor", IMAGE_CURSOR, cx, cy, flags);
      break; /* Crosshair A */
    case GHOST_kStandardCursorCrosshairB:
      cursor = ::LoadImage(module, "crossB_cursor", IMAGE_CURSOR, cx, cy, flags);
      break; /* Diagonal Crosshair B */
    case GHOST_kStandardCursorCrosshairC:
      cursor = ::LoadImage(module, "crossC_cursor", IMAGE_CURSOR, cx, cy, flags);
      break; /* Minimal Crosshair C */
    case GHOST_kStandardCursorBottomSide:
    case GHOST_kStandardCursorUpDown:
      cursor = ::LoadImage(module, "movens_cursor", IMAGE_CURSOR, cx, cy, flags);
      break; /* Double-pointed arrow pointing north and south */
    case GHOST_kStandardCursorLeftSide:
    case GHOST_kStandardCursorLeftRight:
      cursor = ::LoadImage(module, "moveew_cursor", IMAGE_CURSOR, cx, cy, flags);
      break; /* Double-pointed arrow pointing west and east */
    case GHOST_kStandardCursorTopSide:
      cursor = ::LoadImage(NULL, IDC_UPARROW, IMAGE_CURSOR, cx, cy, flags);
      break; /* Vertical arrow */
    case GHOST_kStandardCursorTopLeftCorner:
      cursor = ::LoadImage(NULL, IDC_SIZENWSE, IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorTopRightCorner:
      cursor = ::LoadImage(NULL, IDC_SIZENESW, IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorBottomRightCorner:
      cursor = ::LoadImage(NULL, IDC_SIZENWSE, IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorBottomLeftCorner:
      cursor = ::LoadImage(NULL, IDC_SIZENESW, IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorPencil:
      cursor = ::LoadImage(module, "pencil_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorEraser:
      cursor = ::LoadImage(module, "eraser_cursor", IMAGE_CURSOR, cx, cy, flags);
      break;
    case GHOST_kStandardCursorDestroy:
    case GHOST_kStandardCursorStop:
      cursor = ::LoadImage(module, "forbidden_cursor", IMAGE_CURSOR, cx, cy, flags);
      break; /* Slashed circle */
    case GHOST_kStandardCursorDefault:
      cursor = NULL;
      break;
    default:
      return NULL;
  }

  if (cursor == NULL) {
    cursor = ::LoadImage(NULL, IDC_ARROW, IMAGE_CURSOR, cx, cy, flags);
  }

  return (HCURSOR)cursor;
}

void GHOST_WindowWin32::loadCursor(bool visible, GHOST_TStandardCursor shape) const
{
  if (!visible) {
    while (::ShowCursor(FALSE) >= 0)
      ;
  }
  else {
    while (::ShowCursor(TRUE) < 0)
      ;
  }

  HCURSOR cursor = getStandardCursor(shape);
  if (cursor == NULL) {
    cursor = getStandardCursor(GHOST_kStandardCursorDefault);
  }
  ::SetCursor(cursor);
}

GHOST_TSuccess GHOST_WindowWin32::setWindowCursorVisibility(bool visible)
{
  if (::GetForegroundWindow() == m_hWnd) {
    loadCursor(visible, getCursorShape());
  }

  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_WindowWin32::setWindowCursorGrab(GHOST_TGrabCursorMode mode)
{
  if (!m_hWnd) {
    return GHOST_kFailure;
  }
  if (mode != GHOST_kGrabDisable) {
    if (mode != GHOST_kGrabNormal) {
      m_system->getCursorPosition(m_cursorGrabInitPos[0], m_cursorGrabInitPos[1]);
      setCursorGrabAccum(0, 0);

      if (mode == GHOST_kGrabHide) {
        setWindowCursorVisibility(false);
      }
    }
    updateMouseCapture(OperatorGrab);
  }
  else {
    if (m_cursorGrab == GHOST_kGrabHide) {
      m_system->setCursorPosition(m_cursorGrabInitPos[0], m_cursorGrabInitPos[1]);
      setWindowCursorVisibility(true);
    }
    if (m_cursorGrab != GHOST_kGrabNormal) {
      /* Use to generate a mouse move event, otherwise the last event
       * blender gets can be outside the screen causing menus not to show
       * properly unless the user moves the mouse. */
      int32_t pos[2];
      m_system->getCursorPosition(pos[0], pos[1]);
      m_system->setCursorPosition(pos[0], pos[1]);
    }

    /* Almost works without but important otherwise the mouse GHOST location
     * can be incorrect on exit. */
    setCursorGrabAccum(0, 0);
    m_cursorGrabBounds.m_l = m_cursorGrabBounds.m_r = -1; /* disable */
    updateMouseCapture(OperatorUngrab);
  }

  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_WindowWin32::setWindowCursorShape(GHOST_TStandardCursor cursorShape)
{
  if (::GetForegroundWindow() == m_hWnd) {
    loadCursor(getCursorVisibility(), cursorShape);
  }

  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_WindowWin32::hasCursorShape(GHOST_TStandardCursor cursorShape)
{
  return (getStandardCursor(cursorShape)) ? GHOST_kSuccess : GHOST_kFailure;
}

GHOST_TSuccess GHOST_WindowWin32::getPointerInfo(
    std::vector<GHOST_PointerInfoWin32> &outPointerInfo, WPARAM wParam, LPARAM /*lParam*/)
{
  int32_t pointerId = GET_POINTERID_WPARAM(wParam);
  int32_t isPrimary = IS_POINTER_PRIMARY_WPARAM(wParam);
  GHOST_SystemWin32 *system = (GHOST_SystemWin32 *)GHOST_System::getSystem();
  uint32_t outCount = 0;

  if (!(GetPointerPenInfoHistory(pointerId, &outCount, NULL))) {
    return GHOST_kFailure;
  }

  std::vector<POINTER_PEN_INFO> pointerPenInfo(outCount);
  outPointerInfo.resize(outCount);

  if (!(GetPointerPenInfoHistory(pointerId, &outCount, pointerPenInfo.data()))) {
    return GHOST_kFailure;
  }

  for (uint32_t i = 0; i < outCount; i++) {
    POINTER_INFO pointerApiInfo = pointerPenInfo[i].pointerInfo;
    /* Obtain the basic information from the event. */
    outPointerInfo[i].pointerId = pointerId;
    outPointerInfo[i].isPrimary = isPrimary;

    switch (pointerApiInfo.ButtonChangeType) {
      case POINTER_CHANGE_FIRSTBUTTON_DOWN:
      case POINTER_CHANGE_FIRSTBUTTON_UP:
        outPointerInfo[i].buttonMask = GHOST_kButtonMaskLeft;
        break;
      case POINTER_CHANGE_SECONDBUTTON_DOWN:
      case POINTER_CHANGE_SECONDBUTTON_UP:
        outPointerInfo[i].buttonMask = GHOST_kButtonMaskRight;
        break;
      case POINTER_CHANGE_THIRDBUTTON_DOWN:
      case POINTER_CHANGE_THIRDBUTTON_UP:
        outPointerInfo[i].buttonMask = GHOST_kButtonMaskMiddle;
        break;
      case POINTER_CHANGE_FOURTHBUTTON_DOWN:
      case POINTER_CHANGE_FOURTHBUTTON_UP:
        outPointerInfo[i].buttonMask = GHOST_kButtonMaskButton4;
        break;
      case POINTER_CHANGE_FIFTHBUTTON_DOWN:
      case POINTER_CHANGE_FIFTHBUTTON_UP:
        outPointerInfo[i].buttonMask = GHOST_kButtonMaskButton5;
        break;
      default:
        break;
    }

    outPointerInfo[i].pixelLocation = pointerApiInfo.ptPixelLocation;
    outPointerInfo[i].tabletData.Active = GHOST_kTabletModeStylus;
    outPointerInfo[i].tabletData.Pressure = 1.0f;
    outPointerInfo[i].tabletData.Xtilt = 0.0f;
    outPointerInfo[i].tabletData.Ytilt = 0.0f;
    outPointerInfo[i].time = system->performanceCounterToMillis(pointerApiInfo.PerformanceCount);

    if (pointerPenInfo[i].penMask & PEN_MASK_PRESSURE) {
      outPointerInfo[i].tabletData.Pressure = pointerPenInfo[i].pressure / 1024.0f;
    }

    if (pointerPenInfo[i].penFlags & PEN_FLAG_ERASER) {
      outPointerInfo[i].tabletData.Active = GHOST_kTabletModeEraser;
    }

    if (pointerPenInfo[i].penMask & PEN_MASK_TILT_X) {
      outPointerInfo[i].tabletData.Xtilt = fmin(fabs(pointerPenInfo[i].tiltX / 90.0f), 1.0f);
    }

    if (pointerPenInfo[i].penMask & PEN_MASK_TILT_Y) {
      outPointerInfo[i].tabletData.Ytilt = fmin(fabs(pointerPenInfo[i].tiltY / 90.0f), 1.0f);
    }
  }

  if (!outPointerInfo.empty()) {
    m_lastPointerTabletData = outPointerInfo.back().tabletData;
  }

  return GHOST_kSuccess;
}

void GHOST_WindowWin32::resetPointerPenInfo()
{
  m_lastPointerTabletData = GHOST_TABLET_DATA_NONE;
}

GHOST_Wintab *GHOST_WindowWin32::getWintab() const
{
  return m_wintab;
}

void GHOST_WindowWin32::loadWintab(bool enable)
{
  if (!m_hWnd) {
    return;
  }
  if (!m_wintab) {
    WINTAB_PRINTF("Loading Wintab for window %p\n", m_hWnd);
    if (m_wintab = GHOST_Wintab::loadWintab(m_hWnd)) {
      if (enable) {
        m_wintab->enable();

        /* Focus Wintab if cursor is inside this window. This ensures Wintab is enabled when the
         * tablet is used to change the Tablet API. */
        int32_t x, y;
        if (m_system->getCursorPosition(x, y)) {
          GHOST_Rect rect;
          getClientBounds(rect);

          if (rect.isInside(x, y)) {
            m_wintab->gainFocus();
          }
        }
      }
    }
  }
}

void GHOST_WindowWin32::closeWintab()
{
  WINTAB_PRINTF("Closing Wintab for window %p\n", m_hWnd);
  delete m_wintab;
  m_wintab = NULL;
}

bool GHOST_WindowWin32::usingTabletAPI(GHOST_TTabletAPI api) const
{
  if (m_system->getTabletAPI() == api) {
    return true;
  }
  else if (m_system->getTabletAPI() == GHOST_kTabletAutomatic) {
    if (m_wintab && m_wintab->devicesPresent()) {
      return api == GHOST_kTabletWintab;
    }
    else {
      return api == GHOST_kTabletWinPointer;
    }
  }
  else {
    return false;
  }
}

GHOST_TabletData GHOST_WindowWin32::getTabletData()
{
  if (usingTabletAPI(GHOST_kTabletWintab)) {
    return m_wintab ? m_wintab->getLastTabletData() : GHOST_TABLET_DATA_NONE;
  }
  else {
    return m_lastPointerTabletData;
  }
}

void GHOST_WindowWin32::ThemeRefresh()
{
  if (!m_hWnd) {
    return;
  }
  const GHOST_ThemePaletteWin32 palette = GHOST_ThemeWin32_Palette(false);
  const BOOL dark = palette.dark && !palette.high_contrast;
  /* Use documented Windows 11 attribute 20, with the pre-2004 Windows 10 fallback.
   * Unsupported attributes are harmless on older Windows. High-contrast colors remain native. */
  if (FAILED(DwmSetWindowAttribute(m_hWnd, 20, &dark, sizeof(dark)))) {
    DwmSetWindowAttribute(m_hWnd, 19, &dark, sizeof(dark));
  }
}

void GHOST_WindowWin32::updateDPI()
{
  if (m_directManipulationHelper) {
    m_directManipulationHelper->setDPI(getDPIHint());
  }
}

uint16_t GHOST_WindowWin32::getDPIHint()
{
  if (m_user32) {
    GHOST_WIN32_GetDpiForWindow fpGetDpiForWindow = (GHOST_WIN32_GetDpiForWindow)::GetProcAddress(
        m_user32, "GetDpiForWindow");

    if (fpGetDpiForWindow) {
      return fpGetDpiForWindow(this->m_hWnd);
    }
  }

  return USER_DEFAULT_SCREEN_DPI;
}

/** Reverse the bits in a uint8_t */
static uint8_t uns8ReverseBits(uint8_t ch)
{
  ch = ((ch >> 1) & 0x55) | ((ch << 1) & 0xAA);
  ch = ((ch >> 2) & 0x33) | ((ch << 2) & 0xCC);
  ch = ((ch >> 4) & 0x0F) | ((ch << 4) & 0xF0);
  return ch;
}

#if 0 /* UNUSED */
/** Reverse the bits in a uint16_t */
static uint16_t uns16ReverseBits(uint16_t shrt)
{
  shrt = ((shrt >> 1) & 0x5555) | ((shrt << 1) & 0xAAAA);
  shrt = ((shrt >> 2) & 0x3333) | ((shrt << 2) & 0xCCCC);
  shrt = ((shrt >> 4) & 0x0F0F) | ((shrt << 4) & 0xF0F0);
  shrt = ((shrt >> 8) & 0x00FF) | ((shrt << 8) & 0xFF00);
  return shrt;
}
#endif

GHOST_TSuccess GHOST_WindowWin32::setWindowCustomCursorShape(uint8_t *bitmap,
                                                             uint8_t *mask,
                                                             int sizeX,
                                                             int sizeY,
                                                             int hotX,
                                                             int hotY,
                                                             bool /*canInvertColor*/)
{
  uint32_t andData[32];
  uint32_t xorData[32];
  uint32_t fullBitRow, fullMaskRow;
  int x, y, cols;

  cols = sizeX / 8; /* Number of whole bytes per row (width of bitmap/mask). */
  if (sizeX % 8) {
    cols++;
  }

  if (m_customCursor) {
    DestroyCursor(m_customCursor);
    m_customCursor = NULL;
  }

  memset(&andData, 0xFF, sizeof(andData));
  memset(&xorData, 0, sizeof(xorData));

  for (y = 0; y < sizeY; y++) {
    fullBitRow = 0;
    fullMaskRow = 0;
    for (x = cols - 1; x >= 0; x--) {
      fullBitRow <<= 8;
      fullMaskRow <<= 8;
      fullBitRow |= uns8ReverseBits(bitmap[cols * y + x]);
      fullMaskRow |= uns8ReverseBits(mask[cols * y + x]);
    }
    xorData[y] = fullBitRow & fullMaskRow;
    andData[y] = ~fullMaskRow;
  }

  m_customCursor = ::CreateCursor(::GetModuleHandle(0), hotX, hotY, 32, 32, andData, xorData);
  if (!m_customCursor) {
    return GHOST_kFailure;
  }

  if (::GetForegroundWindow() == m_hWnd) {
    loadCursor(getCursorVisibility(), GHOST_kStandardCursorCustom);
  }

  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_WindowWin32::setProgressBar(float progress)
{
  /* #SetProgressValue sets state to #TBPF_NORMAL automatically. */
  if (m_Bar && S_OK == m_Bar->SetProgressValue(m_hWnd, 10000 * progress, 10000)) {
    return GHOST_kSuccess;
  }

  return GHOST_kFailure;
}

GHOST_TSuccess GHOST_WindowWin32::endProgressBar()
{
  if (m_Bar && S_OK == m_Bar->SetProgressState(m_hWnd, TBPF_NOPROGRESS)) {
    return GHOST_kSuccess;
  }

  return GHOST_kFailure;
}

#ifdef WITH_INPUT_IME
void GHOST_WindowWin32::beginIME(int32_t x, int32_t y, int32_t /*w*/, int32_t h, bool completed)
{
  m_imeInput.BeginIME(m_hWnd, GHOST_Rect(x, y - h, x, y), completed);
}

void GHOST_WindowWin32::endIME()
{
  m_imeInput.EndIME(m_hWnd);
}
#endif /* WITH_INPUT_IME */
