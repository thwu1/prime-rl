"""Expression evaluator with recursive descent over S-expression-like lists."""

import operator
import math

OPERATORS = {
    '+': operator.add,
    '-': operator.sub,
    '*': operator.mul,
    '/': operator.truediv,
    '**': operator.pow,
    '%': operator.mod,
}

FUNCTIONS = {
    'abs': abs,
    'sqrt': math.sqrt,
    'ceil': math.ceil,
    'floor': math.floor,
    'round': round,
}


class EvalError(Exception):
    """Raised when an expression cannot be evaluated."""


class Evaluator:
    """Evaluate nested list expressions with variables, let-bindings,
    conditionals, and function calls."""

    def __init__(self, variables=None, safe_mode=True):
        self.variables = dict(variables) if variables else {}
        self.safe_mode = safe_mode
        self.call_depth = 0
        self.max_depth = 50

    def evaluate(self, expr):
        """Evaluate *expr* and return a numeric result."""
        if isinstance(expr, (int, float)):
            return expr

        if isinstance(expr, str):
            if expr in self.variables:
                return self.variables[expr]
            try:
                return float(expr)
            except ValueError:
                raise EvalError(f"Unknown variable: {expr}")

        if isinstance(expr, list):
            if len(expr) == 0:
                raise EvalError("Empty expression")

            op = expr[0]

            if op == 'let':
                return self._eval_let(expr)
            elif op == 'if':
                return self._eval_if(expr)
            elif op == 'call':
                return self._eval_call(expr)
            elif op in OPERATORS:
                return self._eval_operator(op, expr[1:])
            else:
                raise EvalError(f"Unknown operator: {op}")

        raise EvalError(f"Invalid expression type: {type(expr)}")

    def _eval_operator(self, op, args):
        if len(args) != 2:
            raise EvalError(f"Operator {op} requires 2 arguments")

        left = self.evaluate(args[0])
        right = self.evaluate(args[1])

        if op == '/' and right == 0:
            if self.safe_mode:
                return float('inf')
            raise EvalError("Division by zero")

        if op == '**' and self.safe_mode:
            if abs(right) > 100:
                raise EvalError("Exponent too large")

        return OPERATORS[op](left, right)

    def _eval_let(self, expr):
        if len(expr) != 4:
            raise EvalError("let requires: ['let', name, value, body]")

        _, name, value_expr, body = expr

        if not isinstance(name, str):
            raise EvalError("let variable name must be a string")

        old_value = self.variables.get(name)
        self.variables[name] = self.evaluate(value_expr)

        try:
            result = self.evaluate(body)
        finally:
            if old_value is not None:
                self.variables[name] = old_value
            else:
                del self.variables[name]

        return result

    def _eval_if(self, expr):
        if len(expr) not in (3, 4):
            raise EvalError(
                "if requires: ['if', cond, then] or ['if', cond, then, else]",
            )

        cond = self.evaluate(expr[1])

        if cond:
            return self.evaluate(expr[2])
        elif len(expr) == 4:
            return self.evaluate(expr[3])
        else:
            return 0

    def _eval_call(self, expr):
        if len(expr) < 2:
            raise EvalError("call requires at least a function name")

        func_name = expr[1]
        if func_name not in FUNCTIONS:
            raise EvalError(f"Unknown function: {func_name}")

        self.call_depth += 1
        if self.call_depth > self.max_depth:
            self.call_depth -= 1
            raise EvalError("Maximum call depth exceeded")

        try:
            args = [self.evaluate(a) for a in expr[2:]]
            return FUNCTIONS[func_name](*args)
        except (ValueError, TypeError) as e:
            raise EvalError(f"Function error: {e}") from e
        finally:
            self.call_depth -= 1
