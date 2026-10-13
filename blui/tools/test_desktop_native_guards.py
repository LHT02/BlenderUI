# SPDX-License-Identifier: GPL-2.0-or-later
"""Source guards complement root's native fixture; no GUI/Win32 calls here."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


def body(text, signature):
    start = text.index('{', text.index(signature))
    depth = 1
    for index in range(start + 1, len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if not depth:
            return text[start + 1:index]
    raise AssertionError('Unclosed source function')


class DesktopNativeGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.window = source('intern/ghost/intern/GHOST_WindowWin32.cc')
        cls.system = source('intern/ghost/intern/GHOST_SystemWin32.cc')
        cls.wmwindow = source('source/blender/windowmanager/intern/wm_window.c')

    def test_precise_destroy_and_focus_message_gate(self):
        self.assertIn('if (msg == WM_NCDESTROY && window->isBluiDesktopWindow()', self.system)
        self.assertIn('if (msg == WM_SETFOCUS && window->isBluiDesktopWindow())', self.system)
        destroy = self.system[self.system.index('if (msg == WM_NCDESTROY'):]
        self.assertLess(destroy.index('GWLP_USERDATA, 0'), destroy.index('invalidateBluiDesktopHandle'))

    def test_hidden_desktop_unique_native_instance_not_normal_class(self):
        constructor = body(self.window, 'GHOST_WindowWin32::GHOST_WindowWin32(')
        self.assertIn('desktop_window ? L"BLUI_DesktopWindowClass" : s_windowClassName', constructor)
        self.assertIn('std::atomic<uintptr_t> next_instance', constructor)
        self.assertIn('L"BLUI.DesktopInstance.v1"', constructor)
        self.assertIn('if (desktop_window) {\n    nCmdShow = SW_HIDE;', constructor)
        self.assertIn('if (!(glSettings.flags & (GHOST_glBluiDesktopWindow | GHOST_glBluiPassiveWindow)))',
                      self.system)

    def test_dedicated_class_excludes_private_class_parent_dc(self):
        init = body(self.system, 'GHOST_TSuccess GHOST_SystemWin32::init()')
        self.assertIn('wc.style = CS_HREDRAW | CS_VREDRAW;', init)
        self.assertIn('wc.style &= ~(CS_OWNDC | CS_CLASSDC | CS_PARENTDC)', init)

    def test_child_focus_is_explicit_own_desktop_button_not_hover(self):
        click = body(self.system, 'GHOST_EventButton *GHOST_SystemWin32::processButtonEvent(')
        self.assertIn('type == GHOST_kEventButtonDown && window->isBluiDesktopWindow()', click)
        self.assertIn('& WS_CHILD', click)
        self.assertIn('::SetFocus(window->getHWND())', click)

    def test_gpu_cleanup_preserves_exact_context_and_no_dead_window_activation(self):
        invalidate = body(self.window, 'void GHOST_WindowWin32::invalidateBluiDesktopHandle()')
        self.assertIn('setBluiDesktopCleanupHandles', invalidate)
        self.assertLess(invalidate.index('setBluiDesktopCleanupHandles'), invalidate.index('m_hWnd = nullptr'))
        teardown = body(self.wmwindow, 'static void wm_ghostwindow_destroy(')
        self.assertIn('GHOST_ActivateOpenGLContext(GHOST_GetDrawingContext(win->ghostwin))', teardown)
        self.assertIn('!GHOST_GetValid(win->ghostwin)', teardown)
        wgl = body(source('intern/ghost/intern/GHOST_ContextWGL.cc'),
                   'void GHOST_ContextWGL::setBluiDesktopCleanupHandles(')
        self.assertIn('wglMakeCurrent(m_hDC, m_hGLRC)', wgl)
        self.assertNotIn('wglCreateContext', wgl)

    def test_drop_target_owned_reference_is_released_even_without_hwnd(self):
        destructor = body(self.window, 'GHOST_WindowWin32::~GHOST_WindowWin32()')
        self.assertIn('releaseDropTarget();  /* Also release', destructor)
        release = body(self.window, 'void GHOST_WindowWin32::releaseDropTarget()')
        self.assertIn('if (m_hWnd)', release)
        self.assertIn('m_dropTarget->Release()', release)

    def test_stale_events_close_only_force_and_never_last_window_quit(self):
        event = body(self.wmwindow, 'static bool ghost_event_proc(')
        self.assertIn('desktop_native_lost && type != GHOST_kEventWindowClose', event)
        close = event[event.index('case GHOST_kEventWindowClose:'):]
        self.assertIn('if (desktop_native_lost)', close)
        self.assertLess(close.index('wm_window_close_force'), close.index('wm_window_close(C'))
        force = body(self.wmwindow, 'void wm_window_close_force(')
        self.assertIn('win->blui_shell_role != WM_BLUI_SHELL_DESKTOP', force)

    def test_draw_loop_and_native_swap_skip_lost_desktop(self):
        draw = body(source('source/blender/windowmanager/intern/wm_draw.c'), 'void wm_draw_update(')
        self.assertIn('WM_BLUI_SHELL_DESKTOP', draw)
        self.assertIn('!GHOST_GetValid(win->ghostwin)', draw)
        self.assertIn('m_bluiDesktopWindow && !getValid() ? GHOST_kFailure', self.window)

    def test_orphan_node_removal_requires_exact_temp_marker(self):
        cleanup = body(source('source/blender/windowmanager/intern/wm.c'),
                       'static void wm_blui_orphan_shell_layouts_remove(')
        self.assertIn('screen->temp && (screen->flag & SCREEN_BLUI_DESKTOP_HOST)', cleanup)
        self.assertIn('area->spacetype == SPACE_NODE', cleanup)
        self.assertIn('space->spacetype == SPACE_NODE', cleanup)
        self.assertIn('if (!used)', cleanup)

    def test_private_desktop_screen_layout_not_written_normal_nodes_preserved(self):
        screen = body(source('source/blender/blenkernel/intern/screen.c'), 'static void screen_blend_write(')
        self.assertIn('screen->temp && (screen->flag & SCREEN_BLUI_DESKTOP_HOST)', screen)
        workspace = source('source/blender/blenkernel/intern/workspace.cc')
        write = body(workspace, 'static void workspace_blend_write(')
        self.assertIn('WorkSpace serial_workspace = *workspace', write)
        self.assertIn('WorkSpaceLayout serial_layout = *layout', write)
        self.assertIn('BLO_write_struct_at_address(writer, WorkSpaceLayout, layout, &serial_layout)', write)

    def test_native_fixture_key_events_keep_explicit_region_coordinates(self):
        fixture = source('blui/tools/check_desktop_native_lifecycle.py')
        api = body(source('source/blender/makesrna/intern/rna_wm_api.c'),
                   'static wmEvent *rna_Window_event_add_simulate(')
        self.assertIn('e.xy[0] = x;', api)
        self.assertIn('e.xy[1] = y;', api)
        for value in ('PRESS', 'RELEASE'):
            self.assertIn("type='A', value='" + value + "', x=point[0], y=point[1]", fixture)
        phase = fixture[fixture.index('elif phase == 3:'):]
        self.assertLess(phase.index('bpy.ops.screen.screenshot'), phase.index('assert all(node.select'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
