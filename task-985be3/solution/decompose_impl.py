"""Region decomposition engine — reference solution.

Implements symbolic execution through conditional expressions with
feasibility filtering via Z3 (with brute-force fallback).
"""


import sys
import itertools
import random

sys.path.insert(0, '/app')

from lang import (Const, Var, BinOp, IfExpr, Call, Compare, And, Or, Not,
                  BoolConst, FuncDef, Region, eval_expr, eval_bool)

try:
    from z3 import Int, Solver, sat, Not as Z3Not, And as Z3And, Or as Z3Or
    _HAS_Z3 = True
except ImportError:
    _HAS_Z3 = False


# ─── Boolean negation with De Morgan ────────────────────────────────

_NEG_CMP = {'<': '>=', '<=': '>', '>': '<=', '>=': '<',
            '==': '!=', '!=': '=='}


def _negate(bexpr):
    """Negate a BoolExpr, applying De Morgan's laws."""
    if isinstance(bexpr, Compare):
        return Compare(_NEG_CMP[bexpr.op], bexpr.left, bexpr.right)
    if isinstance(bexpr, And):
        return Or(_negate(bexpr.left), _negate(bexpr.right))
    if isinstance(bexpr, Or):
        return And(_negate(bexpr.left), _negate(bexpr.right))
    if isinstance(bexpr, Not):
        return bexpr.operand
    if isinstance(bexpr, BoolConst):
        return BoolConst(not bexpr.value)
    return Not(bexpr)


# ─── Substitution ───────────────────────────────────────────────────

def _subst_expr(expr, m):
    """Substitute variables in an Expr according to mapping m: name -> Expr."""
    if isinstance(expr, Const):
        return expr
    if isinstance(expr, Var):
        return m.get(expr.name, expr)
    if isinstance(expr, BinOp):
        return BinOp(expr.op, _subst_expr(expr.left, m),
                     _subst_expr(expr.right, m))
    if isinstance(expr, IfExpr):
        return IfExpr(_subst_bool(expr.cond, m),
                      _subst_expr(expr.then_expr, m),
                      _subst_expr(expr.else_expr, m))
    if isinstance(expr, Call):
        return Call(expr.func_name, [_subst_expr(a, m) for a in expr.args])
    return expr


def _subst_bool(b, m):
    """Substitute variables in a BoolExpr."""
    if isinstance(b, Compare):
        return Compare(b.op, _subst_expr(b.left, m),
                       _subst_expr(b.right, m))
    if isinstance(b, And):
        return And(_subst_bool(b.left, m), _subst_bool(b.right, m))
    if isinstance(b, Or):
        return Or(_subst_bool(b.left, m), _subst_bool(b.right, m))
    if isinstance(b, Not):
        return Not(_subst_bool(b.operand, m))
    return b


# ─── Call detection ─────────────────────────────────────────────────

def _has_call(expr):
    """Return True if expr contains any Call node."""
    if isinstance(expr, Call):
        return True
    if isinstance(expr, BinOp):
        return _has_call(expr.left) or _has_call(expr.right)
    if isinstance(expr, IfExpr):
        return _has_call(expr.then_expr) or _has_call(expr.else_expr)
    return False


# ─── Symbolic path enumeration ──────────────────────────────────────

def _paths(expr, cs, funcs, depth):
    """
    Enumerate all execution paths through an expression.

    Yields (constraints_list, leaf_expr) pairs where leaf_expr is free
    of IfExpr nodes.  For Call nodes, inline the function body with
    parameter substitution and recurse (decrementing depth).  When depth
    reaches 0, Call nodes are silently dropped (incomplete region).

    For BinOp whose operands decompose into multiple paths, the Cartesian
    product of left and right paths is taken, combining constraints.
    """
    if isinstance(expr, (Const, Var)):
        yield (list(cs), expr)

    elif isinstance(expr, IfExpr):
        # then branch: add condition
        yield from _paths(expr.then_expr, cs + [expr.cond], funcs, depth)
        # else branch: add negated condition
        yield from _paths(expr.else_expr, cs + [_negate(expr.cond)],
                          funcs, depth)

    elif isinstance(expr, BinOp):
        # Decompose sub-expressions independently, Cartesian-product
        lps = list(_paths(expr.left, [], funcs, depth))
        rps = list(_paths(expr.right, [], funcs, depth))
        for lc, le in lps:
            for rc, re in rps:
                yield (list(cs) + lc + rc, BinOp(expr.op, le, re))

    elif isinstance(expr, Call):
        if funcs and expr.func_name in funcs and depth > 0:
            fn = funcs[expr.func_name]
            m = {p: a for p, a in zip(fn.params, expr.args)}
            body = _subst_expr(fn.body, m)
            yield from _paths(body, cs, funcs, depth - 1)
        # else: incomplete — do not yield

    else:
        yield (list(cs), expr)


# ─── Feasibility checking (Z3) ──────────────────────────────────────

def _expr_to_z3(expr, vs):
    """Convert an Expr to a Z3 ArithRef."""
    if isinstance(expr, Const):
        return expr.value
    if isinstance(expr, Var):
        if expr.name not in vs:
            vs[expr.name] = Int(expr.name)
        return vs[expr.name]
    if isinstance(expr, BinOp):
        l = _expr_to_z3(expr.left, vs)
        r = _expr_to_z3(expr.right, vs)
        if expr.op == '+':
            return l + r
        if expr.op == '-':
            return l - r
        if expr.op == '*':
            return l * r
        if expr.op == '//':
            return l / r
    raise ValueError(f"Cannot convert to Z3: {type(expr)}")


def _bool_to_z3(b, vs):
    """Convert a BoolExpr to a Z3 BoolRef."""
    if isinstance(b, Compare):
        l = _expr_to_z3(b.left, vs)
        r = _expr_to_z3(b.right, vs)
        op = b.op
        if op == '<':
            return l < r
        if op == '<=':
            return l <= r
        if op == '>':
            return l > r
        if op == '>=':
            return l >= r
        if op == '==':
            return l == r
        if op == '!=':
            return l != r
    if isinstance(b, And):
        return Z3And(_bool_to_z3(b.left, vs), _bool_to_z3(b.right, vs))
    if isinstance(b, Or):
        return Z3Or(_bool_to_z3(b.left, vs), _bool_to_z3(b.right, vs))
    if isinstance(b, Not):
        return Z3Not(_bool_to_z3(b.operand, vs))
    if isinstance(b, BoolConst):
        return b.value
    raise ValueError(f"Cannot convert to Z3: {type(b)}")


def _feasible_z3(constraints):
    """Check satisfiability of constraints using Z3."""
    s = Solver()
    vs = {}
    for c in constraints:
        s.add(_bool_to_z3(c, vs))
    return s.check() == sat


# ─── Feasibility checking (brute-force fallback) ────────────────────

def _collect_vars(constraints):
    """Collect variable names from a list of BoolExpr constraints."""
    out = set()

    def ve(e):
        if isinstance(e, Var):
            out.add(e.name)
        elif isinstance(e, BinOp):
            ve(e.left)
            ve(e.right)
        elif isinstance(e, IfExpr):
            vb(e.cond)
            ve(e.then_expr)
            ve(e.else_expr)
        elif isinstance(e, Call):
            for a in e.args:
                ve(a)

    def vb(b):
        if isinstance(b, Compare):
            ve(b.left)
            ve(b.right)
        elif isinstance(b, And):
            vb(b.left)
            vb(b.right)
        elif isinstance(b, Or):
            vb(b.left)
            vb(b.right)
        elif isinstance(b, Not):
            vb(b.operand)

    for c in constraints:
        vb(c)
    return sorted(out)


def _feasible_brute(constraints, params):
    """Check feasibility by exhaustive small-range search + random sampling."""
    vs = _collect_vars(constraints) or list(params)
    if not vs:
        return all(eval_bool(c, {}) for c in constraints)

    # Exhaustive check over small values (catches tight single-point regions)
    small = range(-10, 11)
    for vals in itertools.product(small, repeat=len(vs)):
        env = dict(zip(vs, vals))
        if all(eval_bool(c, env) for c in constraints):
            return True

    # Random sampling for wider ranges
    rng = random.Random(42)
    for _ in range(20000):
        env = {v: rng.randint(-500, 500) for v in vs}
        if all(eval_bool(c, env) for c in constraints):
            return True

    return False


def _feasible(constraints, params):
    """Check if constraints are satisfiable."""
    if not constraints:
        return True
    if _HAS_Z3:
        try:
            return _feasible_z3(constraints)
        except Exception:
            pass
    return _feasible_brute(constraints, params)


# ─── Main entry point ───────────────────────────────────────────────

def decompose(func, funcs=None, unroll_depth=3):
    """
    Perform region decomposition on a function.

    Args:
        func: FuncDef to decompose
        funcs: dict mapping function names to FuncDef (for recursive calls)
        unroll_depth: max times to expand recursive calls

    Returns:
        list of Region objects — only feasible, complete regions
        (invariants free of Call nodes) are included.
    """
    if funcs is None:
        funcs = {}
    fn_map = dict(funcs)
    if func.is_recursive:
        fn_map[func.name] = func

    depth = unroll_depth if func.is_recursive else 0
    raw = list(_paths(func.body, [], fn_map, depth))

    result = []
    for cs, inv in raw:
        # Skip incomplete regions (still have unresolved calls)
        if _has_call(inv):
            continue
        # Skip infeasible regions
        if not _feasible(cs, func.params):
            continue
        result.append(Region(constraints=cs, invariant=inv))

    return result
