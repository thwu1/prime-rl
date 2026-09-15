"""
Mini Effekt -- A free-monad-based interpreter for a language with algebraic
effect handlers, inspired by the Effekt research language.

Programs are constructed using AST node classes and executed via the
Interpreter class. Effects are represented as suspended computations
(free monad), and handlers process these computations by matching
effect names and providing resumption continuations.

"""

from typing import Any, List, Optional, Dict, Callable

# =================== AST Nodes ===================


class Expr:
    """Base class for all AST nodes."""
    pass


class IntLit(Expr):
    def __init__(self, value: int):
        self.value = value


class BoolLit(Expr):
    def __init__(self, value: bool):
        self.value = value


class StrLit(Expr):
    def __init__(self, value: str):
        self.value = value


class UnitLit(Expr):
    pass


class Var(Expr):
    def __init__(self, name: str):
        self.name = name


class Let(Expr):
    """let name = value in body"""
    def __init__(self, name: str, value: Expr, body: Expr):
        self.name = name
        self.value = value
        self.body = body


class LetRec(Expr):
    """Recursive function binding: letrec name = fun(...) => fn_body in body

    The bound function can reference itself by ``name`` within its own body,
    enabling recursive definitions.
    """
    def __init__(self, name: str, func: 'Lam', body: Expr):
        self.name = name
        self.func = func
        self.body = body


class Lam(Expr):
    """fun(params) => body"""
    def __init__(self, params: List[str], body: Expr):
        self.params = params
        self.body = body


class App(Expr):
    """func(args...)"""
    def __init__(self, func: Expr, args: List[Expr]):
        self.func = func
        self.args = args


class If(Expr):
    def __init__(self, cond: Expr, then_br: Expr, else_br: Expr):
        self.cond = cond
        self.then_br = then_br
        self.else_br = else_br


class BinOp(Expr):
    """Binary operation: +, -, *, //, %, ==, !=, <, >, <=, >="""
    def __init__(self, op: str, left: Expr, right: Expr):
        self.op = op
        self.left = left
        self.right = right


class UnaryOp(Expr):
    """Unary operation: not, -"""
    def __init__(self, op: str, operand: Expr):
        self.op = op
        self.operand = operand


class Do(Expr):
    """Perform an effect: do Effect(args...)"""
    def __init__(self, effect: str, args: Optional[List[Expr]] = None):
        self.effect = effect
        self.args = args if args is not None else []


class Handle(Expr):
    """
    try { body }
    with Effect1(params...) { resume => handler_body }
    ...
    [with return(x) { return_body }]
    """
    def __init__(self, body: Expr, handlers: List['HandlerClause'],
                 return_clause: Optional['ReturnClause'] = None):
        self.body = body
        self.handlers = handlers
        self.return_clause = return_clause


class HandlerClause:
    """A single effect handler clause."""
    def __init__(self, effect: str, params: List[str],
                 resume_name: str, body: Expr):
        self.effect = effect
        self.params = params
        self.resume_name = resume_name
        self.body = body


class ReturnClause:
    """Optional return clause for a handler: with return(x) { body }"""
    def __init__(self, param: str, body: Expr):
        self.param = param
        self.body = body


class Seq(Expr):
    """Sequence of expressions; evaluates all, returns the last value."""
    def __init__(self, *exprs):
        self.exprs = list(exprs)


class Print(Expr):
    """Print a value to output (direct I/O, not an algebraic effect)."""
    def __init__(self, value: Expr):
        self.value = value


# =================== Runtime Values ===================


class Unit:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "()"

    def __eq__(self, other):
        return isinstance(other, Unit)

    def __hash__(self):
        return hash("unit")


UNIT = Unit()


class Closure:
    """A function closure capturing its environment."""
    def __init__(self, params, body, env):
        self.params = params
        self.body = body
        self.env = env


class ResumeFn:
    """Wrapper for a resumption continuation function."""
    def __init__(self, fn):
        self.fn = fn


# =================== Free Monad (Computation) ===================


class Computation:
    """Base class for computation values in the free monad."""
    pass


class Pure(Computation):
    """A completed computation carrying a value."""
    def __init__(self, value):
        self.value = value


class Step(Computation):
    """A suspended computation: performs an effect, then continues.

    effect: the effect name (string)
    args:   the effect operation's arguments (list)
    cont:   continuation function  value -> Computation
    """
    def __init__(self, effect: str, args: list, cont: Callable):
        self.effect = effect
        self.args = args
        self.cont = cont


def flat_map(comp: Computation, f: Callable) -> Computation:
    """Monadic bind: comp >>= f"""
    if isinstance(comp, Pure):
        return f(comp.value)
    elif isinstance(comp, Step):
        return Step(comp.effect, comp.args,
                    lambda v, _f=f, _k=comp.cont: flat_map(_k(v), _f))
    else:
        raise RuntimeError(f"Unknown computation type: {type(comp)}")


# =================== Interpreter ===================


class InterpreterError(Exception):
    pass


class UnhandledEffectError(InterpreterError):
    def __init__(self, effect, args):
        self.effect = effect
        self.args = args
        super().__init__(
            f"Unhandled effect: {effect}({', '.join(str(a) for a in args)})")


class Interpreter:
    """Free-monad interpreter for the mini Effekt language."""

    def __init__(self):
        self.output: List[str] = []

    # ---------- evaluation ----------

    def evaluate(self, expr: Expr, env: Dict[str, Any]) -> Computation:
        """Evaluate an expression in an environment, returning a Computation."""

        if isinstance(expr, IntLit):
            return Pure(expr.value)

        elif isinstance(expr, BoolLit):
            return Pure(expr.value)

        elif isinstance(expr, StrLit):
            return Pure(expr.value)

        elif isinstance(expr, UnitLit):
            return Pure(UNIT)

        elif isinstance(expr, Var):
            if expr.name not in env:
                raise InterpreterError(f"Unbound variable: {expr.name}")
            return Pure(env[expr.name])

        elif isinstance(expr, Let):
            return flat_map(
                self.evaluate(expr.value, env),
                lambda v, _e=env, _ex=expr: self.evaluate(
                    _ex.body, {**_e, _ex.name: v}))

        elif isinstance(expr, LetRec):
            closure = Closure(expr.func.params, expr.func.body, dict(env))
            closure.env[expr.name] = closure
            new_env = dict(env)
            new_env[expr.name] = closure
            return self.evaluate(expr.body, new_env)

        elif isinstance(expr, Lam):
            return Pure(Closure(expr.params, expr.body, dict(env)))

        elif isinstance(expr, App):
            return flat_map(
                self.evaluate(expr.func, env),
                lambda f, _a=expr.args, _e=env: self._eval_args(
                    _a, _e, lambda args, _f=f: self._apply(_f, args)))

        elif isinstance(expr, If):
            return flat_map(
                self.evaluate(expr.cond, env),
                lambda c, _e=env, _ex=expr: self.evaluate(
                    _ex.then_br if c else _ex.else_br, _e))

        elif isinstance(expr, BinOp):
            return flat_map(
                self.evaluate(expr.left, env),
                lambda l, _e=env, _ex=expr: flat_map(
                    self.evaluate(_ex.right, _e),
                    lambda r, _l=l, _op=_ex.op: Pure(
                        self._eval_binop(_op, _l, r))))

        elif isinstance(expr, UnaryOp):
            return flat_map(
                self.evaluate(expr.operand, env),
                lambda v, _op=expr.op: Pure(self._eval_unaryop(_op, v)))

        elif isinstance(expr, Do):
            return self._eval_args(
                expr.args, env,
                lambda args, _eff=expr.effect: Step(
                    _eff, args, lambda v: Pure(v)))

        elif isinstance(expr, Handle):
            body_comp = self.evaluate(expr.body, env)
            return self._handle(body_comp, expr.handlers, env,
                                expr.return_clause)

        elif isinstance(expr, Seq):
            return self._eval_seq(expr.exprs, env)

        elif isinstance(expr, Print):
            return flat_map(
                self.evaluate(expr.value, env),
                lambda v: self._do_print(v))

        else:
            raise InterpreterError(
                f"Unknown expression type: {type(expr).__name__}")

    # ---------- helpers ----------

    def _do_print(self, value):
        self.output.append(str(value))
        return Pure(UNIT)

    def _eval_args(self, arg_exprs, env, cont):
        if not arg_exprs:
            return cont([])
        return flat_map(
            self.evaluate(arg_exprs[0], env),
            lambda v, _rest=arg_exprs[1:], _e=env, _c=cont: self._eval_args(
                _rest, _e, lambda vs, _v=v, _cc=_c: _cc([_v] + vs)))

    def _eval_seq(self, exprs, env):
        if not exprs:
            return Pure(UNIT)
        if len(exprs) == 1:
            return self.evaluate(exprs[0], env)
        return flat_map(
            self.evaluate(exprs[0], env),
            lambda _, _rest=exprs[1:], _e=env: self._eval_seq(_rest, _e))

    def _apply(self, func, args):
        if isinstance(func, Closure):
            if len(func.params) != len(args):
                raise InterpreterError(
                    f"Arity mismatch: expected {len(func.params)}, "
                    f"got {len(args)}")
            new_env = dict(func.env)
            for p, a in zip(func.params, args):
                new_env[p] = a
            return self.evaluate(func.body, new_env)
        elif isinstance(func, ResumeFn):
            return func.fn(args[0] if args else UNIT)
        elif callable(func):
            return Pure(func(*args))
        else:
            raise InterpreterError(
                f"Cannot apply non-function: {type(func).__name__}")

    def _eval_binop(self, op, left, right):
        ops = {
            '+':  lambda a, b: a + b,
            '-':  lambda a, b: a - b,
            '*':  lambda a, b: a * b,
            '//': lambda a, b: a // b,
            '%':  lambda a, b: a % b,
            '==': lambda a, b: a == b,
            '!=': lambda a, b: a != b,
            '<':  lambda a, b: a < b,
            '>':  lambda a, b: a > b,
            '<=': lambda a, b: a <= b,
            '>=': lambda a, b: a >= b,
        }
        if op not in ops:
            raise InterpreterError(f"Unknown binary operator: {op}")
        return ops[op](left, right)

    def _eval_unaryop(self, op, val):
        if op == 'not':
            return not val
        if op == '-':
            return -val
        raise InterpreterError(f"Unknown unary operator: {op}")

    # =================== Effect Handler Core ===================

    def _handle(self, comp, handler_clauses, handler_env, return_clause=None):
        """
        Process a computation through a set of effect handler clauses.

        Deep handler semantics: the handler is reinstalled around the
        resumed continuation so subsequent effects in the same body
        are still caught.

        Unmatched effects propagate outward with the handler preserved
        so that later effects in the continuation are still handled.

        If a return clause is present, it transforms the body's natural
        return value (Pure), but does NOT transform handler body results.
        """
        if isinstance(comp, Pure):
            if return_clause is not None:
                ret_env = dict(handler_env)
                ret_env[return_clause.param] = comp.value
                return self.evaluate(return_clause.body, ret_env)
            return Pure(comp.value)

        elif isinstance(comp, Step):
            for clause in handler_clauses:
                if clause.effect == comp.effect:
                    captured_cont = comp.cont

                    def _make_resume(k, _hc=handler_clauses,
                                     _he=handler_env, _rc=return_clause):
                        def _resume(value):
                            return self._handle(k(value), _hc, _he, _rc)
                        return _resume

                    resume = ResumeFn(_make_resume(captured_cont))

                    h_env = dict(handler_env)
                    for param, arg in zip(clause.params, comp.args):
                        h_env[param] = arg
                    h_env[clause.resume_name] = resume

                    return self.evaluate(clause.body, h_env)

            # effect not handled here -- propagate with handler preserved
            return Step(comp.effect, comp.args,
                        lambda v, _k=comp.cont, _hc=handler_clauses,
                               _he=handler_env, _rc=return_clause:
                            self._handle(_k(v), _hc, _he, _rc))

        raise InterpreterError(
            f"Unknown computation type: {type(comp).__name__}")

    # =================== Top-level runner ===================

    def run(self, expr, env=None):
        """Run a program to completion.

        Returns (result_value, output_lines_list).
        Raises UnhandledEffectError for unhandled effects.
        """
        self.output = []
        if env is None:
            env = {}
        comp = self.evaluate(expr, env)
        result = self._execute(comp)
        return result, list(self.output)

    def _execute(self, comp):
        """Drive a computation that should be effect-free to a value."""
        if isinstance(comp, Pure):
            return comp.value
        if isinstance(comp, Step):
            raise UnhandledEffectError(comp.effect, comp.args)
        raise InterpreterError(
            f"Unexpected computation state: {type(comp).__name__}")
