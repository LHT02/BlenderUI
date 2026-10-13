# SPDX-License-Identifier: GPL-2.0-or-later
"""Source safety guards for shell hover classification; GUI behavior is tested natively by root."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def body(text, name):
    start = text.index(name + '(')
    opened = text.index('{', start)
    depth = 0
    for index in range(opened, len(text)):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if not depth:
                return text[opened:index + 1]
    raise AssertionError('Incomplete native function: ' + name)


class ShellUiGuardSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = (ROOT / 'source/blender/editors/interface/interface_handlers.cc').read_text('utf-8')
        cls.wm = (ROOT / 'source/blender/windowmanager/intern/wm_event_system.cc').read_text('utf-8')
        cls.helper = body(cls.ui, 'UI_handler_has_modal_interaction')

    def test_userdata_cast_requires_exact_registered_callback_pair(self):
        cast = self.helper.index('static_cast<const uiHandleButtonData *>')
        for check in ('handler->handle_fn != ui_handler_region_menu',
                      'handler->remove_fn != nullptr', 'handler->head.type != WM_HANDLER_TYPE_UI'):
            self.assertLess(self.helper.index(check), cast)
        registration = self.ui[self.ui.index('if (button_modal_state(state))'):]
        self.assertIn('ui_handler_region_menu,\n                                nullptr,\n                                data,', registration)

    def test_deferred_free_is_checked_before_userdata_can_be_dereferenced(self):
        self.assertLess(self.helper.index('handler->head.flag & WM_HANDLER_DO_FREE'),
                        self.helper.index('static_cast<const uiHandleButtonData *>'))

    def test_popup_search_and_custom_interaction_are_not_idle(self):
        for check in ('data->window != window', 'handler->context.menu', 'data->menu',
                      'data->searchbox', 'data->custom_interaction_handle'):
            self.assertIn(check, self.helper)
        self.assertIn('return true;', self.helper)

    def test_only_highlight_and_exit_are_false_and_edits_have_compile_time_guards(self):
        classifier = body(self.ui, 'ui_button_state_has_modal_interaction')
        self.assertIn('case BUTTON_STATE_HIGHLIGHT:', classifier)
        self.assertIn('case BUTTON_STATE_EXIT:', classifier)
        self.assertIn('return false;', classifier)
        self.assertIn('default:\n      return true;', classifier)
        for state in ('TEXT_EDITING', 'TEXT_SELECTING', 'NUM_EDITING', 'WAIT_RELEASE', 'WAIT_DRAG', 'MENU_OPEN'):
            self.assertIn('static_assert(ui_button_state_has_modal_interaction(BUTTON_STATE_' + state + '));', self.ui)

    def test_normal_and_desktop_node_canvas_guard_stays_conservative(self):
        modal = body(self.wm, 'WM_window_has_modal_interaction')
        gate = modal.index('ELEM(win->blui_shell_role, WM_BLUI_SHELL_NORMAL, WM_BLUI_SHELL_DESKTOP)')
        helper = modal.index('UI_handler_has_modal_interaction(ui_handler, win)')
        self.assertLess(gate, helper)
        self.assertIn('return true;', modal[gate:helper])
        self.assertIn('if (operator_handler->op)', modal)


if __name__ == '__main__':
    unittest.main()
