
"""
Direct-style interpreter for the effect handler language.

Evaluation of basic expressions (literals, binops, conditionals, lambdas,
application, let/def bindings, sequences, print) is complete.

Evaluation of HandleExpr and DoExpr is NOT implemented.
"""

from ast_nodes import *
import sys

sys.setrecursionlimit(50000)


class EffektError(Exception):
    pass


class Closure:
    """A function closure."""
    __slots__ = ['params', 'body', 'env', 'name', 'is_recursive']

    def __init__(self, params, body, env, name=None, is_recursive=False):
        self.params = params
        self.body = body
        self.env = env
        self.name = name
        self.is_recursive = is_recursive

    def __repr__(self):
        n = self.name or "anonymous"
        return f"<function {n}>"


class UnitValue:
    """The unit value singleton."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "unit"


UNIT = UnitValue()


class Interpreter:
    def __init__(self):
        self.output_lines = []
        self.effect_registry = {}

    def run(self, program):
        """Run a complete program. Returns (result_value, output_string)."""
        self.output_lines = []
        self.effect_registry = {}

        for eff in program.effects:
            self.effect_registry[eff.name] = [op.name for op in eff.operations]

        env = {}
        result = self.eval_expr(program.main, env)
        return result, "\n".join(self.output_lines)

    def eval_expr(self, expr, env):
        """Evaluate an expression in the given environment."""

        if isinstance(expr, IntLit):
            return expr.value

        if isinstance(expr, BoolLit):
            return expr.value

        if isinstance(expr, StringLit):
            return expr.value

        if isinstance(expr, Unit):
            return UNIT

        if isinstance(expr, Var):
            if expr.name not in env:
                raise EffektError(f"Unbound variable: {expr.name}")
            return env[expr.name]

        if isinstance(expr, BinOp):
            left = self.eval_expr(expr.left, env)
            right = self.eval_expr(expr.right, env)
            return self._binop(expr.op, left, right)

        if isinstance(expr, UnaryOp):
            val = self.eval_expr(expr.operand, env)
            if expr.op == '-':
                return -val
            if expr.op == 'not':
                return not val
            raise EffektError(f"Unknown unary op: {expr.op}")

        if isinstance(expr, IfExpr):
            cond = self.eval_expr(expr.cond, env)
            if cond:
                return self.eval_expr(expr.then_branch, env)
            else:
                return self.eval_expr(expr.else_branch, env)

        if isinstance(expr, Lambda):
            return Closure(expr.params, expr.body, dict(env))

        if isinstance(expr, App):
            func = self.eval_expr(expr.func, env)
            args = [self.eval_expr(a, env) for a in expr.args]
            return self._apply(func, args)

        if isinstance(expr, Let):
            val = self.eval_expr(expr.value, env)
            new_env = dict(env)
            new_env[expr.name] = val
            return self.eval_expr(expr.body, new_env)

        if isinstance(expr, DefBinding):
            closure = Closure(expr.params, expr.value, dict(env),
                              name=expr.name, is_recursive=True)
            new_env = dict(env)
            new_env[expr.name] = closure
            closure.env = dict(new_env)
            return self.eval_expr(expr.body, new_env)

        if isinstance(expr, Seq):
            result = UNIT
            for e in expr.exprs:
                result = self.eval_expr(e, env)
            return result

        if isinstance(expr, Print):
            val = self.eval_expr(expr.value, env)
            self._print_val(val)
            return UNIT

        if isinstance(expr, HandleExpr):
            return self._eval_handle(expr, env)

        if isinstance(expr, DoExpr):
            return self._eval_do(expr, env)

        raise EffektError(f"Unknown expression type: {type(expr).__name__}")

    def _eval_handle(self, expr, env):
        """Evaluate a handle expression."""
        raise NotImplementedError("HandleExpr evaluation not yet implemented")

    def _eval_do(self, expr, env):
        """Evaluate a do expression."""
        raise NotImplementedError("DoExpr evaluation not yet implemented")

    def _apply(self, func, args):
        """Apply a function to arguments."""
        if isinstance(func, Closure):
            if len(func.params) != len(args):
                raise EffektError(
                    f"Arity mismatch: {func} expects {len(func.params)} args, "
                    f"got {len(args)}")
            new_env = dict(func.env)
            for p, a in zip(func.params, args):
                new_env[p] = a
            return self.eval_expr(func.body, new_env)
        raise EffektError(f"Cannot apply non-function: {func}")

    def _binop(self, op, left, right):
        ops = {
            '+': lambda a, b: a + b,
            '-': lambda a, b: a - b,
            '*': lambda a, b: a * b,
            '/': lambda a, b: a // b,
            '%': lambda a, b: a % b,
            '==': lambda a, b: a == b,
            '!=': lambda a, b: a != b,
            '<': lambda a, b: a < b,
            '>': lambda a, b: a > b,
            '<=': lambda a, b: a <= b,
            '>=': lambda a, b: a >= b,
            '++': lambda a, b: self._to_string(a) + self._to_string(b),
        }
        if op not in ops:
            raise EffektError(f"Unknown binary operator: {op}")
        return ops[op](left, right)

    def _to_string(self, val):
        if val is UNIT:
            return "unit"
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, Closure):
            return "<function>"
        return str(val)

    def _print_val(self, val):
        self.output_lines.append(self._to_string(val))
