# SPDX-License-Identifier: GPL-2.0-or-later
"""Focused native GIL safety source checks; no Python/native GUI calls in tests."""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


def function(text, signature):
    opening = text.index('{', text.index(signature))
    depth = 1
    for index in range(opening + 1, len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if not depth:
            return text[opening + 1:index]
    raise AssertionError('Unclosed function: ' + signature)


class PythonGilGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.utils = source('source/blender/python/generic/py_capi_utils.c')
        cls.interface = source('source/blender/python/intern/bpy_interface.c')

    def test_predicate_checks_this_threads_gil_without_allocating_thread_dict(self):
        query = function(self.utils, 'bool PyC_IsInterpreterActive(void)')
        self.assertRegex(query, r'return\s+Py_IsInitialized\(\)\s*&&\s*PyGILState_Check\(\)\s*;')
        for call in ('PyThreadState_GetDict', '_PyThreadState_UncheckedGet', 'PyThreadState_Get',
                     'PyDict_New', 'PyGILState_Ensure', 'PyGILState_Release'):
            self.assertNotRegex(query, r'\b' + call + r'\s*\(')

    def test_all_three_real_consumers_keep_balanced_conditional_ensure_release(self):
        signatures = ('void BPY_context_dict_clear_members_array(', 'void BPY_text_free_code(',
                      'int BPY_context_member_get(')
        self.assertEqual(self.interface.count('const bool use_gil = !PyC_IsInterpreterActive();'), 3)
        for signature in signatures:
            block = function(self.interface, signature)
            self.assertIn('const bool use_gil = !PyC_IsInterpreterActive();', block)
            self.assertEqual(block.count('gilstate = PyGILState_Ensure();'), 1)
            self.assertEqual(block.count('PyGILState_Release(gilstate);'), 1)
            self.assertRegex(block, r'if \(use_gil\)\s*\{\s*gilstate = PyGILState_Ensure\(\);')
            self.assertRegex(block, r'if \(use_gil\)\s*\{\s*PyGILState_Release\(gilstate\);')

    def test_context_dictionary_allocations_occur_inside_locked_interval(self):
        block = function(self.interface, 'void BPY_context_dict_clear_members_array(')
        acquired, released = block.index('PyGILState_Ensure()'), block.index('PyGILState_Release(')
        for operation in ('PyDict_Copy(', 'PyUnicode_FromString(', '_PyDict_Pop(', 'Py_DECREF('):
            self.assertLess(acquired, block.index(operation))
            self.assertLess(block.rindex(operation), released)

    def test_generic_diagnostic_helpers_return_before_unlocked_python_calls(self):
        for signature in ('void PyC_LineSpit(', 'void PyC_StackSpit(', 'void PyC_FileAndNum_Safe('):
            block = function(self.utils, signature)
            self.assertIn('if (!PyC_IsInterpreterActive())', block)
            self.assertLess(block.index('return;'), block.index('PyC_FileAndNum(')
                            if 'PyC_FileAndNum(' in block else block.index('PyGILState_Ensure('))

    def test_python_operators_still_release_and_restore_gil_for_workers(self):
        block = function(source('source/blender/python/intern/bpy_operator.c'), 'static PyObject *pyop_call(')
        self.assertIn('#ifdef BPY_RELEASE_GIL', block)
        self.assertLess(block.index('PyEval_SaveThread()'), block.index('WM_operator_call_py('))
        self.assertLess(block.index('WM_operator_call_py('), block.index('PyEval_RestoreThread(ts)'))

    def test_nested_region_callback_still_acquires_gil_before_python_and_balances_it(self):
        draw = function(source('source/blender/python/intern/bpy_rna_callback.c'), 'static void cb_region_draw(')
        self.assertLess(draw.index('bpy_context_set('), draw.index('PyObject_CallObject('))
        self.assertLess(draw.index('PyObject_CallObject('), draw.index('bpy_context_clear('))
        enter = function(self.interface, 'void bpy_context_set(')
        leave = function(self.interface, 'void bpy_context_clear(')
        self.assertIn('*gilstate = PyGILState_Ensure();', enter)
        self.assertIn('PyGILState_Release(*gilstate);', leave)

    def test_screenshot_really_redraws_windows_and_background_callback_is_not_disabled(self):
        data = function(source('source/blender/editors/screen/screendump.c'), 'static int screenshot_data_create(')
        self.assertIn('WM_redraw_windows(C)', data)
        background = source('scripts/modules/blui_desktop/background.py')
        self.assertIn("draw_handler_add(_draw, (), 'WINDOW', 'PRE_VIEW')", background)
        fixture = source('blui/tools/check_desktop_hover_restore_native.py')
        self.assertNotIn('background.unregister(', fixture)
        self.assertNotIn('draw_handler_remove(', fixture)
        self.assertNotIn('mock.patch.object(background', fixture)

    def screenshot_count(self, value=None):
        tree = ast.parse(source('blui/tools/check_desktop_hover_restore_native.py'))
        method = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                      and item.name == 'screenshots_per_phase')
        env = {} if value is None else {'BLUI_DESKTOP_QA_SCREENSHOTS': value}
        namespace = {'os': SimpleNamespace(environ=env)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual QA screenshot bounded config>', 'exec'), namespace)
        return namespace['screenshots_per_phase']()

    def test_real_screenshot_stress_counts_preserve_default_two_and_bound_four_eight(self):
        self.assertEqual(self.screenshot_count(), 1)
        for total in (2, 4, 8):
            self.assertEqual(self.screenshot_count(str(total)) * 2, total)
        for value in ('0', '1', '3', '16', '-2', 'oops'):
            with self.assertRaises(ValueError):
                self.screenshot_count(value)


if __name__ == '__main__':
    unittest.main(verbosity=2)
