"""
AST types and concrete evaluators for a simple functional language.

This module defines the expression language used for region decomposition.
Do NOT modify the type definitions or evaluator functions.
"""


from dataclasses import dataclass
from typing import List, Dict, Optional, Union


# === Expression AST ===

@dataclass
class Const:
    """Integer constant."""
    value: int

@dataclass
class Var:
    """Variable reference."""
    name: str

@dataclass
class BinOp:
    """Binary arithmetic operation: +, -, *, //"""
    op: str
    left: 'Expr'
    right: 'Expr'

@dataclass
class IfExpr:
    """Conditional expression: if cond then then_expr else else_expr"""
    cond: 'BoolExpr'
    then_expr: 'Expr'
    else_expr: 'Expr'

@dataclass
class Call:
    """Recursive function call."""
    func_name: str
    args: list  # list of Expr

Expr = Union[Const, Var, BinOp, IfExpr, Call]


# === Boolean Expression AST ===

@dataclass
class Compare:
    """Comparison: <, <=, >, >=, ==, !="""
    op: str
    left: Expr
    right: Expr

@dataclass
class And:
    """Logical conjunction."""
    left: 'BoolExpr'
    right: 'BoolExpr'

@dataclass
class Or:
    """Logical disjunction."""
    left: 'BoolExpr'
    right: 'BoolExpr'

@dataclass
class Not:
    """Logical negation."""
    operand: 'BoolExpr'

@dataclass
class BoolConst:
    """Boolean constant."""
    value: bool

BoolExpr = Union[Compare, And, Or, Not, BoolConst]


# === Function Definition ===

@dataclass
class FuncDef:
    """Function definition with optional recursion flag."""
    name: str
    params: list  # list of str (parameter names)
    body: Expr
    is_recursive: bool = False


# === Region ===

@dataclass
class Region:
    """A region in the decomposition.

    Attributes:
        constraints: list of BoolExpr whose conjunction defines this region
        invariant: Expr giving the function's symbolic output in this region
    """
    constraints: list  # list of BoolExpr
    invariant: Expr


# === Concrete Evaluators ===

def eval_expr(expr, env, funcs=None, depth=100):
    """Evaluate an expression to a concrete integer value.

    Args:
        expr: An Expr AST node
        env: dict mapping variable names to int values
        funcs: optional dict mapping function names to FuncDef (for recursive calls)
        depth: maximum recursion depth
    """
    if isinstance(expr, Const):
        return expr.value
    elif isinstance(expr, Var):
        return env[expr.name]
    elif isinstance(expr, BinOp):
        l = eval_expr(expr.left, env, funcs, depth)
        r = eval_expr(expr.right, env, funcs, depth)
        if expr.op == '+':
            return l + r
        elif expr.op == '-':
            return l - r
        elif expr.op == '*':
            return l * r
        elif expr.op == '//':
            return l // r if r != 0 else 0
        else:
            raise ValueError(f"Unknown op: {expr.op}")
    elif isinstance(expr, IfExpr):
        if eval_bool(expr.cond, env, funcs, depth):
            return eval_expr(expr.then_expr, env, funcs, depth)
        else:
            return eval_expr(expr.else_expr, env, funcs, depth)
    elif isinstance(expr, Call):
        if funcs is None or expr.func_name not in funcs:
            raise ValueError(f"Unknown function: {expr.func_name}")
        if depth <= 0:
            raise RecursionError("Max depth exceeded")
        func = funcs[expr.func_name]
        new_env = {}
        for p, a in zip(func.params, expr.args):
            new_env[p] = eval_expr(a, env, funcs, depth)
        return eval_expr(func.body, new_env, funcs, depth - 1)
    else:
        raise TypeError(f"Unknown expr: {type(expr)}")


def eval_bool(bexpr, env, funcs=None, depth=100):
    """Evaluate a boolean expression to a concrete truth value."""
    if isinstance(bexpr, Compare):
        l = eval_expr(bexpr.left, env, funcs, depth)
        r = eval_expr(bexpr.right, env, funcs, depth)
        if bexpr.op == '<':
            return l < r
        elif bexpr.op == '<=':
            return l <= r
        elif bexpr.op == '>':
            return l > r
        elif bexpr.op == '>=':
            return l >= r
        elif bexpr.op == '==':
            return l == r
        elif bexpr.op == '!=':
            return l != r
        else:
            raise ValueError(f"Unknown comparison: {bexpr.op}")
    elif isinstance(bexpr, And):
        return (eval_bool(bexpr.left, env, funcs, depth)
                and eval_bool(bexpr.right, env, funcs, depth))
    elif isinstance(bexpr, Or):
        return (eval_bool(bexpr.left, env, funcs, depth)
                or eval_bool(bexpr.right, env, funcs, depth))
    elif isinstance(bexpr, Not):
        return not eval_bool(bexpr.operand, env, funcs, depth)
    elif isinstance(bexpr, BoolConst):
        return bexpr.value
    else:
        raise TypeError(f"Unknown bool expr: {type(bexpr)}")
