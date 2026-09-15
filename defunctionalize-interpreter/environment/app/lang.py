
"""
Mini functional language: AST, values, and a direct recursive interpreter.

Language features:
  - Integer and boolean literals
  - Binary operators: +, -, *, //, %, ==, !=, <, >, <=, >=
  - Conditional expressions (if/then/else)
  - Lambda abstraction (single parameter)
  - Function application
  - Let bindings
  - Recursive function bindings (letrec)
"""

from dataclasses import dataclass
from typing import Union


# ========================== AST ==========================

@dataclass(frozen=True)
class Var:
    name: str

@dataclass(frozen=True)
class IntLit:
    value: int

@dataclass(frozen=True)
class BoolLit:
    value: bool

@dataclass(frozen=True)
class BinOp:
    op: str
    left: 'Expr'
    right: 'Expr'

@dataclass(frozen=True)
class If:
    cond: 'Expr'
    then_branch: 'Expr'
    else_branch: 'Expr'

@dataclass(frozen=True)
class Lam:
    param: str
    body: 'Expr'

@dataclass(frozen=True)
class App:
    func: 'Expr'
    arg: 'Expr'

@dataclass(frozen=True)
class Let:
    name: str
    value: 'Expr'
    body: 'Expr'

@dataclass(frozen=True)
class LetRec:
    """Recursive function binding.
    Binds `name` to a function with parameter `func_param` and body `func_body`,
    where `func_body` may refer to `name` for recursion. Then evaluates `body`."""
    name: str
    func_param: str
    func_body: 'Expr'
    body: 'Expr'

Expr = Union[Var, IntLit, BoolLit, BinOp, If, Lam, App, Let, LetRec]


# ========================== Values ==========================

@dataclass
class VClosure:
    param: str
    body: Expr
    env: dict

@dataclass
class VRecClosure:
    name: str
    param: str
    body: Expr
    env: dict

Value = Union[int, bool, VClosure, VRecClosure]


# ========================== Operator helper ==========================

def apply_op(op: str, left, right):
    """Apply a binary operator to two values."""
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
    return ops[op](left, right)


# ========================== Direct interpreter ==========================

def _apply_func(func_val, arg_val):
    """Apply a closure or recursive closure to an argument."""
    if isinstance(func_val, VRecClosure):
        new_env = dict(func_val.env)
        new_env[func_val.name] = func_val
        new_env[func_val.param] = arg_val
        return eval_direct(func_val.body, new_env)
    elif isinstance(func_val, VClosure):
        new_env = dict(func_val.env)
        new_env[func_val.param] = arg_val
        return eval_direct(func_val.body, new_env)
    else:
        raise TypeError(f"Cannot apply non-function: {func_val}")


def eval_direct(expr: Expr, env: dict = None) -> Value:
    """Evaluate an expression by direct recursion.
    WARNING: uses Python's call stack — will crash on deeply recursive programs."""
    if env is None:
        env = {}
    if isinstance(expr, IntLit):
        return expr.value
    elif isinstance(expr, BoolLit):
        return expr.value
    elif isinstance(expr, Var):
        return env[expr.name]
    elif isinstance(expr, BinOp):
        left = eval_direct(expr.left, env)
        right = eval_direct(expr.right, env)
        return apply_op(expr.op, left, right)
    elif isinstance(expr, If):
        cond = eval_direct(expr.cond, env)
        if cond:
            return eval_direct(expr.then_branch, env)
        else:
            return eval_direct(expr.else_branch, env)
    elif isinstance(expr, Lam):
        return VClosure(expr.param, expr.body, dict(env))
    elif isinstance(expr, App):
        func_val = eval_direct(expr.func, env)
        arg_val = eval_direct(expr.arg, env)
        return _apply_func(func_val, arg_val)
    elif isinstance(expr, Let):
        val = eval_direct(expr.value, env)
        new_env = dict(env)
        new_env[expr.name] = val
        return eval_direct(expr.body, new_env)
    elif isinstance(expr, LetRec):
        rec = VRecClosure(expr.name, expr.func_param, expr.func_body, dict(env))
        rec.env[expr.name] = rec
        new_env = dict(env)
        new_env[expr.name] = rec
        return eval_direct(expr.body, new_env)
    else:
        raise TypeError(f"Unknown expression: {type(expr)}")


# ========================== Test programs ==========================

PROGRAMS = [
    # (name, expression, expected_result)

    ("arithmetic",
     BinOp('+', IntLit(3), BinOp('*', IntLit(4), IntLit(5))),
     23),

    ("let_binding",
     Let('x', IntLit(10), BinOp('+', Var('x'), IntLit(5))),
     15),

    ("lambda_apply",
     App(Lam('x', BinOp('*', Var('x'), Var('x'))), IntLit(7)),
     49),

    ("higher_order",
     Let('apply', Lam('f', Lam('x', App(Var('f'), Var('x')))),
         App(App(Var('apply'),
                 Lam('n', BinOp('+', Var('n'), IntLit(1)))),
             IntLit(41))),
     42),

    ("factorial",
     LetRec('fact', 'n',
            If(BinOp('==', Var('n'), IntLit(0)),
               IntLit(1),
               BinOp('*', Var('n'),
                     App(Var('fact'), BinOp('-', Var('n'), IntLit(1))))),
            App(Var('fact'), IntLit(10))),
     3628800),

    ("fibonacci",
     LetRec('fib', 'n',
            If(BinOp('<', Var('n'), IntLit(2)),
               Var('n'),
               BinOp('+',
                     App(Var('fib'), BinOp('-', Var('n'), IntLit(1))),
                     App(Var('fib'), BinOp('-', Var('n'), IntLit(2))))),
            App(Var('fib'), IntLit(20))),
     6765),

    ("composition",
     Let('compose',
         Lam('f', Lam('g', Lam('x',
             App(Var('f'), App(Var('g'), Var('x')))))),
         Let('double', Lam('x', BinOp('*', IntLit(2), Var('x'))),
             Let('inc', Lam('x', BinOp('+', Var('x'), IntLit(1))),
                 App(App(App(Var('compose'), Var('double')),
                         Var('inc')),
                     IntLit(20))))),
     42),

    ("nested_if",
     If(BoolLit(True),
        If(BoolLit(False), IntLit(0), IntLit(1)),
        IntLit(2)),
     1),

    ("nested_let",
     Let('x', IntLit(5),
         Let('y', BinOp('*', Var('x'), IntLit(2)),
             Let('z', BinOp('+', Var('y'), IntLit(3)),
                 Var('z')))),
     13),

    ("church_booleans",
     Let('true_c', Lam('a', Lam('b', Var('a'))),
         Let('false_c', Lam('a', Lam('b', Var('b'))),
             Let('not_c', Lam('p',
                     App(App(Var('p'), Var('false_c')), Var('true_c'))),
                 App(App(App(Var('not_c'), Var('false_c')),
                         IntLit(1)),
                     IntLit(0))))),
     1),

    ("curried_recursive",
     LetRec('pow', 'b',
            Lam('e',
                If(BinOp('==', Var('e'), IntLit(0)),
                   IntLit(1),
                   BinOp('*', Var('b'),
                         App(App(Var('pow'), Var('b')),
                             BinOp('-', Var('e'), IntLit(1)))))),
            App(App(Var('pow'), IntLit(3)), IntLit(7))),
     2187),

    ("closure_capture",
     Let('make_adder', Lam('x', Lam('y', BinOp('+', Var('x'), Var('y')))),
         Let('add5', App(Var('make_adder'), IntLit(5)),
             Let('add10', App(Var('make_adder'), IntLit(10)),
                 BinOp('+',
                       App(Var('add5'), IntLit(3)),
                       App(Var('add10'), IntLit(7)))))),
     25),

    ("gcd",
     LetRec('gcd', 'a',
            Lam('b',
                If(BinOp('==', Var('b'), IntLit(0)),
                   Var('a'),
                   App(App(Var('gcd'), Var('b')),
                       BinOp('%', Var('a'), Var('b'))))),
            App(App(Var('gcd'), IntLit(48)), IntLit(18))),
     6),
]
