# SPDX-License-Identifier: GPL-2.0-or-later
"""Calculator service security/bounds tests without bpy, GUI or user-file writes."""
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'scripts' / 'modules'))
from blui_desktop import safe_math


class DesktopCalculator(unittest.TestCase):
    def test_arithmetic_precedence_and_real_functions(self):
        examples = {'2+3*4': 14, '(2+3)*4': 20, '-2**2': -4,
                    '7//2': 3, '7%2': 1, '2**10': 1024,
                    'sqrt(81)+abs(-3)': 12, 'round(1.23456,3)': 1.235,
                    'log(8,2)': 3, 'log10(100)': 2,
                    'min(3,2,1)+max(3,2,1)': 4,
                    'sin(pi/2)': 1, 'cos(tau)': 1, 'ln(e)': 1,
                    'atan2(1,1)': math.pi / 4,
                    'round(1234,-2)': 1200, 'ceil(1.1)+floor(2.9)': 4}
        for expression, expected in examples.items():
            with self.subTest(expression=expression):
                self.assertAlmostEqual(safe_math.calculate(expression), expected)

    def test_compact_format_preserves_precision_and_normalizes_negative_zero(self):
        self.assertEqual(safe_math.format_result(-0.0), '0')
        self.assertEqual(safe_math.format_result(12), '12')
        self.assertEqual(safe_math.format_result(1 / 3), '0.333333333333333')
        self.assertEqual(safe_math.format_result(1e100), '1e+100')

    def test_rejects_all_non_numeric_and_executable_syntax(self):
        rejected = ['True', 'None', '"file"', '1j', '[1,2]', '{1:2}', '(1,2)',
                    '1<2', '1 and 2', '1 if True else 2', '1<<20', '~1',
                    '().__class__', '(1).real', 'math.sqrt(4)', 'pi.__class__',
                    'open("a")', '__import__("os")', 'eval("1")',
                    'exec("1")', '(lambda: 1)()', 'abs(*[1])',
                    'round(1,ndigits=2)', '[x for x in (1,2)]', '(x:=1)',
                    'globals()', 'sin.__call__(0)', '__builtins__', 'nan', 'inf']
        # Unexpected execution, filesystem access or imports must not happen.
        with mock.patch('builtins.eval', side_effect=AssertionError('No eval')), \
             mock.patch('builtins.exec', side_effect=AssertionError('No exec')), \
             mock.patch('builtins.open', side_effect=AssertionError('No IO')):
            for expression in rejected:
                with self.subTest(expression=expression):
                    with self.assertRaises(safe_math.CalculationError):
                        safe_math.calculate(expression)

    def test_errors_are_short_readable_and_not_python_tracebacks(self):
        examples = {'1/0': 'Division by zero',
                    'sqrt(-1)': 'Value is outside the function domain',
                    'log(0)': 'Value is outside the function domain',
                    'round(1,1.5)': 'Rounding precision must be between -12 and 12',
                    'sqrt(1,2)': 'Incorrect number of function arguments',
                    '1+': 'Invalid calculator expression', '': 'Enter an expression'}
        for expression, error in examples.items():
            with self.subTest(expression=expression):
                with self.assertRaises(safe_math.CalculationError) as caught:
                    safe_math.calculate(expression)
                self.assertEqual(str(caught.exception), error)

    def test_expression_depth_node_count_length_and_function_cost_are_bounded(self):
        examples = ['1' * (safe_math.MAX_EXPRESSION + 1),
                    '-(' * (safe_math.MAX_DEPTH + 1) + '1' + ')' * (safe_math.MAX_DEPTH + 1),
                    '+'.join('1' for _ in range(safe_math.MAX_NODES)),
                    '+'.join('sqrt(1)' for _ in range(20))]
        for expression in examples:
            with self.subTest(length=len(expression)):
                with self.assertRaises(safe_math.CalculationError):
                    safe_math.calculate(expression)

    def test_numbers_and_powers_cannot_allocate_giant_integers(self):
        for expression in ('1e101', '1e309', '9' * 300, '10**101',
                           '2**1000000', '0.5**-1001', '(-1)**0.5',
                           'exp(1000)', '1e100*10', '0**-1', 'round(1,1000000)'):
            with self.subTest(expression=expression):
                with self.assertRaises(safe_math.CalculationError):
                    safe_math.calculate(expression)
        self.assertEqual(safe_math.calculate('10**100'), 1e100)
        self.assertEqual(safe_math.calculate('2**-1000'), 2.0 ** -1000)

    def test_invalid_external_values_are_rejected(self):
        for value in (None, b'1+2', 4, True, [], {}, 'bad\x00expression'):
            with self.subTest(value=value):
                with self.assertRaises(safe_math.CalculationError):
                    safe_math.calculate(value)
        for value in (float('inf'), float('nan'), True, complex(1), 10 ** 1000):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(safe_math.CalculationError):
                    safe_math.format_result(value)


if __name__ == '__main__':
    unittest.main(verbosity=2)
