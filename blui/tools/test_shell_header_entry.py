# SPDX-License-Identifier: GPL-2.0-or-later
"""Source-only shell header guards; no bpy, GUI, native calls, or build.

These tests prevent accidental removal of the implementation gates.  A passing
source check is not evidence of rendered arrows or real mouse/RNA behavior;
check_shell_header_native.py is the separately executed, owned-window fixture.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
AREA_PATH = 'source/blender/editors/screen/area.cc'
OPS_PATH = 'source/blender/editors/screen/screen_ops.c'
SHELL_ROLES = {
    'WM_BLUI_SHELL_TASKBAR', 'WM_BLUI_SHELL_STARTMENU',
    'WM_BLUI_SHELL_TASK_CHOOSER', 'WM_BLUI_SHELL_TASK_PREVIEW',
}
HEADER_TYPES = {'RGN_TYPE_HEADER', 'RGN_TYPE_TOOL_HEADER'}


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


def function(text, name):
    """Read the real definition, not an earlier invocation of the function."""
    pattern = r'\b' + re.escape(name) + r'\s*\([^;{}]*\)\s*\{'
    match = re.search(pattern, text)
    if match is None:
        raise AssertionError('Missing function definition: ' + name)
    opening = match.end() - 1
    depth = 1
    for index in range(opening + 1, len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if not depth:
            return text[opening + 1:index]
    raise AssertionError('Unclosed function definition: ' + name)


class ShellHeaderEntrySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.area = source(AREA_PATH)
        cls.ops = source(OPS_PATH)

    def test_policy_is_exact_four_roles_and_two_header_types(self):
        predicate = function(self.area, 'region_is_blui_shell_header')
        self.assertEqual(set(re.findall(r'WM_BLUI_SHELL_[A-Z_]+', predicate)), SHELL_ROLES)
        self.assertEqual(set(re.findall(r'RGN_TYPE_[A-Z_]+', predicate)), HEADER_TYPES)
        self.assertIn('win->blui_shell_role', predicate)
        self.assertIn('region->regiontype', predicate)
        self.assertNotIn('screen->temp', predicate)
        self.assertNotIn('blui_shell_ui', predicate)
        # NORMAL/DESKTOP must not be treated as uneditable auxiliary shell UI.
        self.assertNotIn('WM_BLUI_SHELL_NORMAL', predicate)
        self.assertNotIn('WM_BLUI_SHELL_DESKTOP', predicate)

    def test_policy_nulls_fail_without_dereferencing(self):
        predicate = function(self.area, 'region_is_blui_shell_header')
        short_circuit = re.search(r'\bwin\s*&&\s*region\s*&&', predicate)
        explicit_null = re.search(r'if\s*\(\s*(?:!win\s*\|\|\s*!region|'
                                  r'win\s*==\s*nullptr\s*\|\|\s*'
                                  r'region\s*==\s*nullptr)\s*\)\s*\{\s*'
                                  r'return\s+false\s*;', predicate)
        self.assertTrue(short_circuit or explicit_null,
                        'The shared predicate must explicitly reject null window/region.')

    def test_policy_is_internal_shared_c_and_cpp_export(self):
        internal = source('source/blender/editors/screen/screen_intern.h')
        self.assertRegex(internal, r'bool\s+region_is_blui_shell_header\s*\('
                         r'\s*const\s+(?:struct\s+)?wmWindow\s*\*\s*win\s*,\s*'
                         r'const\s+(?:struct\s+)?ARegion\s*\*\s*region\s*\)\s*;')
        self.assertIn('extern "C"', internal)

    def test_header_azones_are_not_created_and_scroll_azones_remain(self):
        add = function(self.area, 'region_azones_add')
        gate = add.index('region_is_blui_shell_header(win, region)')
        edges = add.index('region_azones_add_edge(')
        self.assertLess(gate, edges)
        self.assertIn('return;', add[gate:edges])
        self.assertIn('region_azones_scrollbars_init(area, region)', add)
        self.assertIn('fullscreen_azone_init(area, region)', add)
        scroll = function(self.area, 'region_azones_scrollbars_init')
        self.assertNotIn('region_is_blui_shell_header', scroll)
        self.assertIn('V2D_SCROLL_VERTICAL', scroll)
        self.assertIn('V2D_SCROLL_HORIZONTAL', scroll)

    def test_both_generation_paths_pass_current_window(self):
        for name in ('ED_area_init', 'ED_area_update_region_sizes'):
            block = function(self.area, name)
            self.assertIn('region_azones_add(win, screen, area, region)', block, name)
        self.assertEqual(self.area.count('region_azones_add(win, screen, area, region)'), 2)

    def test_init_rehides_rna_override_before_layout_geometry(self):
        init = function(self.area, 'ED_area_init')
        gate = init.index('region_is_blui_shell_header(win, region)')
        geometry = init.index('region_rect_recursive(')
        self.assertLess(gate, geometry)
        self.assertIn('region->flag |= RGN_FLAG_HIDDEN', init[gate:geometry])
        self.assertLess(init.index('region->type ='), gate)

    def test_size_refresh_rehides_rna_override_before_layout_geometry(self):
        resize = function(self.area, 'ED_area_update_region_sizes')
        gate = resize.index('region_is_blui_shell_header(win, region)')
        geometry = resize.index('region_rect_recursive(')
        self.assertLess(gate, geometry)
        self.assertIn('region->flag |= RGN_FLAG_HIDDEN', resize[gate:geometry])

    def test_old_header_azones_are_not_drawn(self):
        draw = function(self.area, 'region_draw_azones')
        gate = draw.index('region_is_blui_shell_header(win, az->region)')
        self.assertIn('az->type == AZONE_REGION', draw[:gate])
        self.assertIn('continue;', draw[gate:draw.index('BLI_rcti_init(&azrct')])
        actual_draw = function(self.area, 'ED_region_do_draw')
        self.assertRegex(actual_draw, r'region_draw_azones\(\s*'
                         r'(?:win|CTX_wm_window\(C\))\s*,\s*area\s*,\s*region\s*\)')

    def test_toggle_impl_cannot_unhide_a_shell_header(self):
        toggle = function(self.area, 'region_toggle_hidden')
        gate = toggle.index('region_is_blui_shell_header(CTX_wm_window(C), region)')
        mutation = toggle.index('region->flag ^= RGN_FLAG_HIDDEN')
        self.assertLess(gate, mutation)
        self.assertIn('return;', toggle[gate:mutation])
        self.assertIn('ED_region_visibility_change_update(C, area, region)', toggle)

    def test_old_azone_poll_and_invoke_cannot_enter_hidden_modal(self):
        poll = function(self.ops, 'actionzone_area_poll')
        self.assertIn('region_is_blui_shell_header(win, az->region)', poll)
        self.assertIn('az->type == AZONE_REGION', poll)
        invoke = function(self.ops, 'actionzone_invoke')
        gate = invoke.index('region_is_blui_shell_header(')
        self.assertLess(gate, invoke.index('MEM_callocN('))
        self.assertIn('OPERATOR_CANCELLED', invoke[gate:invoke.index('MEM_callocN(')])
        # Actual region scaling remains implemented for ordinary editors.
        scale = function(self.ops, 'region_scale_invoke')
        self.assertIn('WM_event_add_modal_handler(C, op)', scale)
        self.assertIn('OPERATOR_RUNNING_MODAL', scale)

    def test_explicit_region_toggle_operator_rejects_shell_headers(self):
        toggle = function(self.ops, 'region_toggle_exec')
        gate = toggle.index('region_is_blui_shell_header(CTX_wm_window(C), region)')
        mutation = toggle.index('ED_region_toggle_hidden(C, region)')
        self.assertLess(gate, mutation)
        self.assertIn('return OPERATOR_CANCELLED;', toggle[gate:mutation])
        self.assertIn('RNA_property_is_set', toggle)

    def test_header_context_menu_has_no_shell_header_toggle_items(self):
        menu = function(self.ops, 'ED_screens_header_tools_menu_create')
        gate = menu.index('region_is_blui_shell_header(CTX_wm_window(C),')
        controls = menu.index('"show_region_header"')
        self.assertLess(gate, controls)
        self.assertIn('BKE_area_find_region_type(area, RGN_TYPE_HEADER)', menu[gate:controls])
        self.assertIn('return;', menu[gate:controls])
        self.assertIn('"show_region_tool_header"', menu)

    def test_no_global_region_toggle_preference_is_modified(self):
        gate = function(self.area, 'region_azone_edge_poll')
        self.assertIn('is_hidden && (U.app_flag & USER_APP_HIDE_REGION_TOGGLE)', gate)
        self.assertNotIn('blui_shell_role', gate)
        for text in (self.area, self.ops):
            self.assertNotRegex(text, r'U\.app_flag\s*[|&^]?=\s*[^;]*'
                                r'USER_APP_HIDE_REGION_TOGGLE')

    def test_native_constructor_still_hides_shell_header(self):
        constructor = function(source('source/blender/windowmanager/intern/wm_window.c'),
                               'wm_blui_shell_window_create_exec')
        self.assertRegex(constructor, r'if\s*\(region->regiontype\s*==\s*'
                         r'RGN_TYPE_HEADER\)\s*\{\s*'
                         r'region->flag\s*\|=\s*RGN_FLAG_HIDDEN;')
        self.assertIn('ED_screen_refresh(wm, win)', constructor)
        self.assertIn('desktop ? SPACE_NODE : SPACE_INFO', constructor)


if __name__ == '__main__':
    unittest.main()
