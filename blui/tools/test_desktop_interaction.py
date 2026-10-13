# SPDX-License-Identifier: GPL-2.0-or-later
"""Desktop-only lifecycle gate regressions. No bpy, GUI, or native mutation."""
import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


def body(text, name):
    opening = text.index('{', text.index(name + '('))
    depth = 1
    for index in range(opening + 1, len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if not depth:
            return text[opening + 1:index]
    raise AssertionError('Unclosed function ' + name)


def busy_function():
    tree = ast.parse(source('scripts/modules/blui_desktop/desktop_service.py'))
    adapter = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == 'RNAWindows')
    method = next(item for item in adapter.body if isinstance(item, ast.FunctionDef) and item.name == 'busy')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual RNAWindows.busy>', 'exec'), namespace)
    return namespace['busy']


class DesktopInteractionTests(unittest.TestCase):
    def test_desktop_has_no_unneeded_explorer_progress_com(self):
        text = source('intern/ghost/intern/GHOST_WindowWin32.cc')
        start = text.index('if (!m_bluiDesktopWindow) {')
        block = text[start:text.index('/* Initialize Direct Manipulation. */', start)]
        self.assertIn('CoCreateInstance', block)
        self.assertIn('IID_ITaskbarList3', block)
        self.assertIn('m_Bar(NULL)', text)
        self.assertIn('if (m_Bar) {', text)

    def busy(self, windows, path_drag=False):
        module = ModuleType('bpy')
        module.context = SimpleNamespace(window_manager=SimpleNamespace(
            windows=windows, blui_has_path_drag=path_drag))
        with mock.patch.dict(sys.modules, {'bpy': module}):
            return busy_function()(None)

    def test_unpressed_highlight_releases_desktop_lifecycle_not_old_guard(self):
        for role in ('NORMAL', 'DESKTOP', 'TASKBAR'):
            window = SimpleNamespace(blui_shell_role=role, blui_has_modal_interaction=True,
                                     blui_has_desktop_interaction=False)
            self.assertFalse(self.busy([window]))
            self.assertTrue(window.blui_has_modal_interaction)

    def test_real_interaction_in_any_window_blocks_lifecycle(self):
        idle = SimpleNamespace(blui_has_desktop_interaction=False, blui_has_modal_interaction=True)
        active = SimpleNamespace(blui_has_desktop_interaction=True, blui_has_modal_interaction=True)
        self.assertTrue(self.busy([idle, active]))
        self.assertTrue(self.busy([active, idle]))

    def test_path_drag_blocks_even_with_no_window(self):
        self.assertTrue(self.busy([], path_drag=True))
        self.assertFalse(self.busy([]))

    def test_older_or_unknown_binary_fails_closed(self):
        self.assertTrue(self.busy([SimpleNamespace(blui_has_modal_interaction=True)]))
        self.assertFalse(self.busy([SimpleNamespace(blui_has_modal_interaction=False)]))
        self.assertTrue(self.busy([SimpleNamespace()]))

    def test_native_new_gate_reuses_precise_ui_and_preserves_real_handlers(self):
        text = source('source/blender/windowmanager/intern/wm_event_system.cc')
        gate = body(text, 'WM_window_has_desktop_interaction')
        for check in ('BLI_listbase_is_empty(&wm->drags)', 'wm_window_has_held_mouse_input(win)',
                      'operator_handler->op', 'UI_handler_has_modal_interaction(ui_handler, win)',
                      'handler->type != WM_HANDLER_TYPE_KEYMAP'):
            self.assertIn(check, gate)
        self.assertNotIn('blui_shell_role', gate)
        old = body(text, 'WM_window_has_modal_interaction')
        self.assertIn('ELEM(win->blui_shell_role, WM_BLUI_SHELL_NORMAL, WM_BLUI_SHELL_DESKTOP)', old)
        self.assertNotIn('WM_window_has_desktop_interaction', old)

    def test_native_held_input_reads_actual_state_not_stale_eventstate(self):
        held = body(source('intern/ghost/intern/GHOST_C-api.cc'), 'GHOST_WindowHasHeldMouseInput')
        for check in ('mode != GHOST_kGrabDisable', 'GetCapture() == hwnd',
                      'GetAsyncKeyState(button) & 0x8000', 'VK_XBUTTON1', 'VK_XBUTTON2'):
            self.assertIn(check, held)
        self.assertNotIn('eventstate', held)
        self.assertNotIn('m_nPressedButtons', held)

    def test_rna_is_read_only_without_dna_or_handler_pointer_exposure(self):
        text = source('source/blender/makesrna/intern/rna_wm.c')
        start = text.index('RNA_def_property(srna, "blui_has_desktop_interaction"')
        prop = text[start:text.index('static const EnumPropertyItem shell_roles', start)]
        self.assertIn('RNA_def_property_clear_flag(prop, PROP_EDITABLE)', prop)
        self.assertNotIn('RNA_def_property_boolean_sdna', prop)
        getter = body(text, 'rna_Window_blui_has_desktop_interaction_get')
        self.assertIn('GS(ptr->owner_id->name) == ID_WM', getter)
        self.assertIn('WM_window_has_desktop_interaction(manager', getter)

    def test_node_thumbnail_and_session_gates_still_use_original_guard(self):
        runtime = source('scripts/modules/blui_desktop/runtime.py')
        self.assertNotIn('blui_has_desktop_interaction', runtime)
        self.assertIn('blui_has_modal_interaction', runtime)
        helper = body(source('source/blender/editors/interface/interface_handlers.cc'),
                      'UI_handler_has_modal_interaction')
        for check in ('handler->handle_fn != ui_handler_region_menu', 'data->menu',
                      'data->searchbox', 'data->custom_interaction_handle'):
            self.assertIn(check, helper)


if __name__ == '__main__':
    unittest.main(verbosity=2)
