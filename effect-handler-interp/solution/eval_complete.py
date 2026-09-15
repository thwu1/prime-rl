
"""
Direct-style interpreter for the effect handler language.
Complete implementation with HandleExpr and DoExpr support.

Uses replay-based multi-shot delimited continuations:
- DoExpr raises a PerformEffect exception to unwind to the handler
- HandleExpr catches PerformEffect and builds a resume function
- Resume re-executes the body, replaying previously handled operations
  with their recorded return values, then handles the next new operation
- This supports multi-shot (resume called multiple times) because each
  call does an independent replay from scratch
"""

from ast_nodes import *
import sys

sys.setrecursionlimit(50000)


class EffektError(Exception):
    pass


class PerformEffect(Exception):
    """Raised by _eval_do to transfer control to the nearest handler."""
    def __init__(self, op_name, args):
        self.op_name = op_name
        self.args = args


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


class NativeFn:
    """Wraps a Python callable as a language-level function."""
    def __init__(self, func, name="<native>"):
        self.func = func
        self.name = name

    def __repr__(self):
        return f"<native {self.name}>"


class UnitValue:
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
        # Handler stack: list of handler frame dicts
        self._handler_stack = []

    def run(self, program):
        self.output_lines = []
        self.effect_registry = {}
        self._handler_stack = []

        for eff in program.effects:
            self.effect_registry[eff.name] = [op.name for op in eff.operations]

        result = self.eval_expr(program.main, {})
        return result, "\n".join(self.output_lines)

    def eval_expr(self, expr, env):
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

    def _eval_do(self, expr, env):
        """
        Evaluate do Op(args).

        Evaluates arguments, then checks the handler stack for replay.
        If we are in replay mode and this operation has a recorded value,
        return that value. Otherwise, raise PerformEffect to unwind to
        the handler.
        """
        args = [self.eval_expr(a, env) for a in expr.args]

        # Check if any handler on the stack handles this operation and has
        # a replay value for it
        handler_idx = self._find_handler(expr.op_name)
        if handler_idx is None:
            raise EffektError(f"Unhandled effect operation: {expr.op_name}")

        frame = self._handler_stack[handler_idx]
        ctx = frame['replay_ctx']
        idx = ctx['idx']

        if idx < len(ctx['log']):
            # Replay mode: return recorded value
            _, recorded_val = ctx['log'][idx]
            ctx['idx'] = idx + 1
            return recorded_val
        else:
            # New operation: raise to handler
            ctx['idx'] = idx + 1
            raise PerformEffect(expr.op_name, args)

    def _eval_handle(self, expr, env):
        """
        Evaluate handle { body } with Effect { clauses }.

        Installs a handler frame, runs the body, and if an operation is
        performed, catches it, builds a resume function, and evaluates
        the handler clause.
        """
        clauses = {}
        for clause in expr.op_clauses:
            clauses[clause.op_name] = clause

        handled_ops = set(clauses.keys())

        return self._run_handled_body(
            expr.body, env, expr.effect_name, clauses,
            expr.return_clause, handled_ops, replay_log=[]
        )

    def _run_handled_body(self, body, env, effect_name, clauses,
                          return_clause, handled_ops, replay_log):
        """Execute body under this handler with the given replay log."""
        handler_frame = {
            'effect_name': effect_name,
            'handled_ops': handled_ops,
            'clauses': clauses,
            'return_clause': return_clause,
            'env': env,
            'body': body,
            'replay_ctx': {
                'log': list(replay_log),
                'idx': 0,
            },
        }

        self._handler_stack.append(handler_frame)
        try:
            result = self.eval_expr(body, env)
        except PerformEffect as pe:
            # Find the handler that should handle this
            handler_idx = self._find_handler_for_perform(pe.op_name)

            if handler_idx is None:
                # No handler found — should not happen if _find_handler worked
                self._handler_stack.pop()
                raise

            frame = self._handler_stack[handler_idx]
            if frame is not handler_frame:
                # Not our handler — pop ourselves and re-raise
                self._handler_stack.pop()
                raise

            # We caught it — pop our frame
            self._handler_stack.pop()

            # Build replay log up to this point
            replay_so_far = list(handler_frame['replay_ctx']['log'][:])

            # Build resume function
            interp = self

            def make_resume(replay_prefix, op_name, frame_data):
                def resume_fn(val):
                    new_log = replay_prefix + [(op_name, val)]
                    return interp._run_handled_body(
                        frame_data['body'],
                        frame_data['env'],
                        frame_data['effect_name'],
                        frame_data['clauses'],
                        frame_data['return_clause'],
                        frame_data['handled_ops'],
                        replay_log=new_log,
                    )
                return resume_fn

            resume = make_resume(replay_so_far, pe.op_name, {
                'body': body,
                'env': env,
                'effect_name': effect_name,
                'clauses': clauses,
                'return_clause': return_clause,
                'handled_ops': handled_ops,
            })

            resume_wrapped = NativeFn(resume, "resume")

            clause = clauses[pe.op_name]
            clause_env = dict(env)
            for p, a in zip(clause.params, pe.args):
                clause_env[p] = a
            clause_env[clause.resume_name] = resume_wrapped

            return self.eval_expr(clause.body, clause_env)
        else:
            # Body completed normally — pop our frame
            self._handler_stack.pop()

            # Apply return clause
            if return_clause:
                ret_env = dict(env)
                ret_env[return_clause.param] = result
                return self.eval_expr(return_clause.body, ret_env)
            return result

    def _find_handler(self, op_name):
        """Find innermost handler that handles op_name."""
        for i in range(len(self._handler_stack) - 1, -1, -1):
            if op_name in self._handler_stack[i]['handled_ops']:
                return i
        return None

    def _find_handler_for_perform(self, op_name):
        """Find innermost handler for a raised PerformEffect."""
        for i in range(len(self._handler_stack) - 1, -1, -1):
            if op_name in self._handler_stack[i]['handled_ops']:
                return i
        return None

    def _apply(self, func, args):
        if isinstance(func, Closure):
            if len(func.params) != len(args):
                raise EffektError(
                    f"Arity mismatch: {func} expects {len(func.params)} args, "
                    f"got {len(args)}")
            new_env = dict(func.env)
            for p, a in zip(func.params, args):
                new_env[p] = a
            return self.eval_expr(func.body, new_env)
        if isinstance(func, NativeFn):
            if len(args) != 1:
                raise EffektError(
                    f"{func.name} expects 1 argument, got {len(args)}")
            return func.func(args[0])
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
        if isinstance(val, (Closure, NativeFn)):
            return "<function>"
        return str(val)

    def _print_val(self, val):
        self.output_lines.append(self._to_string(val))
