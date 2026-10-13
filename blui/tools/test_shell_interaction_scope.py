# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the actual runtime guard functions with fake windows, without importing bpy."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

RUNTIME = Path(__file__).resolve().parents[2] / 'scripts/modules/blui_desktop/runtime.py'


def guards(windows):
    tree = ast.parse(RUNTIME.read_text('utf-8'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name in ('interaction_busy', 'shell_interaction_busy')]
    if len(selected) != 2:
        raise AssertionError('Runtime must retain both normal and shell guard APIs')
    namespace = {'bpy': SimpleNamespace(context=SimpleNamespace(
        window_manager=SimpleNamespace(windows=windows)))}
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(RUNTIME), 'exec'), namespace)
    return namespace['interaction_busy'], namespace['shell_interaction_busy']


def window(role='NORMAL', held=False):
    return SimpleNamespace(blui_shell_role=role, blui_has_modal_interaction=held)


class ShellInteractionScopeTests(unittest.TestCase):
    def test_empty_window_manager_is_not_busy(self):
        document, shell = guards([])
        self.assertFalse(document(None))
        self.assertFalse(shell())

    def test_normal_hover_or_modal_does_not_starve_private_shell_lists(self):
        document, shell = guards([window(held=True), window('STARTMENU')])
        self.assertTrue(document(None), 'Normal document/node guard must stay conservative')
        self.assertFalse(shell(), 'Unrelated NORMAL window must not starve shell async UI')

    def test_no_shell_windows_is_false_even_with_busy_normal_editor(self):
        document, shell = guards([window(held=True), window(held=True)])
        self.assertTrue(document(None))
        self.assertFalse(shell())

    def test_all_native_shell_roles_preserve_held_interaction_blocking(self):
        for role in ('TASKBAR', 'STARTMENU', 'TASK_CHOOSER', 'TASK_PREVIEW'):
            with self.subTest(role=role):
                document, shell = guards([window(), window(role, True)])
                self.assertTrue(document(None))
                self.assertTrue(shell(), 'Shell editing/held input must prevent RNA/window changes')

    def test_idle_shells_do_not_block_either_guard(self):
        document, shell = guards([window(), window('TASKBAR'), window('STARTMENU')])
        self.assertFalse(document(None))
        self.assertFalse(shell())

    def test_busy_shell_is_not_ignored_when_other_shells_are_idle(self):
        document, shell = guards([window('TASKBAR'), window('STARTMENU', True), window('TASK_PREVIEW')])
        self.assertTrue(document(None))
        self.assertTrue(shell())

    def test_shell_guard_does_not_read_unrelated_normal_modal_rna(self):
        class UnrelatedNormal:
            blui_shell_role = 'NORMAL'
            @property
            def blui_has_modal_interaction(self):
                raise AssertionError('Shell guard read unrelated NORMAL document state')
        _document, shell = guards([UnrelatedNormal(), window('STARTMENU')])
        self.assertFalse(shell())


if __name__ == '__main__':
    unittest.main()
