# SPDX-License-Identifier: GPL-2.0-or-later
"""Small, bounded numeric expression interpreter; no Python execution or IO.

All arithmetic uses finite floats. In particular, exponentiation cannot allocate
huge Python integers and calls can only resolve the explicit math table below.
"""
import ast
import math
import operator

MAX_EXPRESSION = 512
MAX_NODES = 128
MAX_DEPTH = 24
MAX_COST = 128
MAX_MAGNITUDE = 1e100
MAX_EXPONENT = 1000


class CalculationError(ValueError):
    """Short, translatable input error rather than a Python traceback."""


def _number(value):
    if type(value) not in (int, float):
        raise CalculationError('Only real numbers are supported')
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise CalculationError('Number is out of range') from None
    if not math.isfinite(result) or abs(result) > MAX_MAGNITUDE:
        raise CalculationError('Number is out of range')
    return result


def _power(base, exponent):
    if abs(exponent) > MAX_EXPONENT:
        raise CalculationError('Exponent is out of range')
    return math.pow(base, exponent)


def _round(value, digits=0.0):
    if not digits.is_integer() or abs(digits) > 12:
        raise CalculationError('Rounding precision must be between -12 and 12')
    return round(value, int(digits))


_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: _power,
}
_CONSTANTS = {'pi': math.pi, 'e': math.e, 'tau': math.tau}
_FUNCTIONS = {
    'sqrt': (math.sqrt, 1, 1),
    'sin': (math.sin, 1, 1), 'cos': (math.cos, 1, 1), 'tan': (math.tan, 1, 1),
    'asin': (math.asin, 1, 1), 'acos': (math.acos, 1, 1), 'atan': (math.atan, 1, 1),
    'atan2': (math.atan2, 2, 2),
    'log': (math.log, 1, 2), 'ln': (math.log, 1, 1),
    'log10': (math.log10, 1, 1), 'log2': (math.log2, 1, 1),
    'exp': (math.exp, 1, 1), 'abs': (abs, 1, 1),
    'floor': (math.floor, 1, 1), 'ceil': (math.ceil, 1, 1),
    'round': (_round, 1, 2), 'min': (min, 2, 8), 'max': (max, 2, 8),
}


def calculate(expression):
    """Return a finite float, or a readable CalculationError within strict bounds."""
    if not isinstance(expression, str):
        raise CalculationError('Invalid calculator expression')
    if len(expression) > MAX_EXPRESSION:
        raise CalculationError('Expression is too long')
    expression = expression.strip()
    if not expression:
        raise CalculationError('Enter an expression')
    try:
        root = ast.parse(expression, mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        raise CalculationError('Invalid calculator expression') from None
    if sum(1 for _node in ast.walk(root)) > MAX_NODES:
        raise CalculationError('Expression is too complex')

    cost = 0

    def visit(node, depth=0):
        nonlocal cost
        cost += 1
        if depth > MAX_DEPTH or cost > MAX_COST:
            raise CalculationError('Expression is too complex')
        if isinstance(node, ast.Constant):
            return _number(node.value)
        if isinstance(node, ast.Name) and node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.UAdd, ast.USub):
            value = visit(node.operand, depth + 1)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            return _number(_BINARY[type(node.op)](left, right))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = _FUNCTIONS.get(node.func.id)
            if not function or node.keywords:
                raise CalculationError('Unsupported calculator operation')
            call, minimum, maximum = function
            if not minimum <= len(node.args) <= maximum:
                raise CalculationError('Incorrect number of function arguments')
            cost += 4
            if cost > MAX_COST:
                raise CalculationError('Expression is too complex')
            args = [visit(arg, depth + 1) for arg in node.args]
            return _number(call(*args))
        raise CalculationError('Unsupported calculator operation')

    try:
        return _number(visit(root.body))
    except CalculationError:
        raise
    except ZeroDivisionError:
        raise CalculationError('Division by zero') from None
    except OverflowError:
        raise CalculationError('Number is out of range') from None
    except (ValueError, TypeError):
        raise CalculationError('Value is outside the function domain') from None
    except RecursionError:
        raise CalculationError('Expression is too complex') from None


def format_result(value):
    """Stable compact display while retaining useful double-precision digits."""
    value = _number(value)
    return '0' if value == 0 else format(value, '.15g')
