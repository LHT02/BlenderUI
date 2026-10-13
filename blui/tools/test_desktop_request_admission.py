# SPDX-License-Identifier: GPL-2.0-or-later
"""Client/worker allowlists must agree; pure extraction never spawns a helper."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'scripts/modules/blui_desktop'


def arity(filename):
    tree = ast.parse((SOURCE / filename).read_text(encoding='utf-8'))
    values = [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'arity' for target in node.targets)]
    assert len(values) == 1
    return ast.literal_eval(values[0])


class AdmissionTests(unittest.TestCase):
    def test_client_and_worker_accept_exact_same_requests(self):
        self.assertEqual(arity('client.py'), arity('worker.py'))

    def test_current_shell_operations_are_admitted(self):
        values = arity('client.py')
        for action, count in (('start_capabilities', 0), ('start_location', 1),
                              ('taskbar_settings_load', 1), ('taskbar_settings_save', 2)):
            self.assertEqual(values[action], count)


if __name__ == '__main__':
    unittest.main()
