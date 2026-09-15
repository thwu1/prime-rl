"""Tests for the region decomposition engine."""


import sys
import pytest

sys.path.insert(0, '/app')

from lang import (Const, Var, BinOp, IfExpr, Call, Compare, And, Or, Not,
                  BoolConst, FuncDef, Region, eval_expr, eval_bool)


# ─── Test function builders (independent of examples.py) ─────────────


def _mk_simple():
    """f(x) = if x>99 then 100 elif x>20 then x+9 elif x>-2 then 103 else 99"""
    return FuncDef('f', ['x'], IfExpr(
        Compare('>', Var('x'), Const(99)), Const(100),
        IfExpr(Compare('>', Var('x'), Const(20)),
               BinOp('+', Var('x'), Const(9)),
               IfExpr(Compare('>', Var('x'), Const(-2)),
                      Const(103), Const(99)))))


def _mk_dead():
    """h(x) = if x>10 then (if x<5 then 999 else x*2) else x+1"""
    return FuncDef('h', ['x'], IfExpr(
        Compare('>', Var('x'), Const(10)),
        IfExpr(Compare('<', Var('x'), Const(5)),
               Const(999), BinOp('*', Var('x'), Const(2))),
        BinOp('+', Var('x'), Const(1))))


def _mk_multi():
    """g(x,y) = if x>y then x-y elif x==y then 0 else y-x"""
    return FuncDef('g', ['x', 'y'], IfExpr(
        Compare('>', Var('x'), Var('y')),
        BinOp('-', Var('x'), Var('y')),
        IfExpr(Compare('==', Var('x'), Var('y')),
               Const(0), BinOp('-', Var('y'), Var('x')))))


def _mk_nested():
    """classify(x,y) -> 9 quadrant/axis/origin regions"""
    def if3(v, a, b, c):
        return IfExpr(Compare('>', v, Const(0)), a,
                      IfExpr(Compare('==', v, Const(0)), b, c))
    return FuncDef('classify', ['x', 'y'], IfExpr(
        Compare('>', Var('x'), Const(0)),
        if3(Var('y'), Const(1), Const(2), Const(3)),
        IfExpr(Compare('==', Var('x'), Const(0)),
               if3(Var('y'), Const(4), Const(5), Const(6)),
               if3(Var('y'), Const(7), Const(8), Const(9)))))


def _mk_recursive():
    """sum_to(n) = if n<=0 then 0 else n + sum_to(n-1)"""
    return FuncDef('sum_to', ['n'], IfExpr(
        Compare('<=', Var('n'), Const(0)), Const(0),
        BinOp('+', Var('n'),
              Call('sum_to', [BinOp('-', Var('n'), Const(1))]))),
        is_recursive=True)


# ─── Helpers ─────────────────────────────────────────────────────────


def _matches(region, env):
    """True if all constraints of a region hold for the given env."""
    return all(eval_bool(c, env) for c in region.constraints)


def _check_correctness(regions, func, envs, funcs=None):
    """For each env, at least one region must match and its invariant
    must equal the direct evaluation of the function body."""
    for env in envs:
        direct = eval_expr(func.body, env, funcs)
        matching = [r for r in regions if _matches(r, env)]
        assert len(matching) >= 1, (
            f"env={env}: no region matches (direct={direct})")
        ok = any(eval_expr(r.invariant, env) == direct for r in matching)
        assert ok, (
            f"env={env}: expected {direct}, no matching region produced it")


# ─── Tests ───────────────────────────────────────────────────────────


class TestSimpleFunction:
    """4-region function from Imandra documentation."""

    def test_region_count(self):
        from decompose import decompose
        r = decompose(_mk_simple())
        assert len(r) == 4, f"Expected 4 regions, got {len(r)}"

    def test_correctness(self):
        from decompose import decompose
        func = _mk_simple()
        regions = decompose(func)
        envs = [{'x': x} for x in range(-50, 200)]
        _check_correctness(regions, func, envs)


class TestDeadBranch:
    """Function with an infeasible path that must be eliminated."""

    def test_region_count(self):
        from decompose import decompose
        r = decompose(_mk_dead())
        assert len(r) == 2, (
            f"Expected 2 regions (x>10 && x<5 is infeasible), got {len(r)}")

    def test_correctness(self):
        from decompose import decompose
        func = _mk_dead()
        regions = decompose(func)
        envs = [{'x': x} for x in range(-50, 50)]
        _check_correctness(regions, func, envs)


class TestMultiArgument:
    """Two-argument function with 3 regions."""

    def test_region_count(self):
        from decompose import decompose
        r = decompose(_mk_multi())
        assert len(r) == 3, f"Expected 3 regions, got {len(r)}"

    def test_correctness(self):
        from decompose import decompose
        func = _mk_multi()
        regions = decompose(func)
        envs = [{'x': x, 'y': y}
                for x in range(-10, 11) for y in range(-10, 11)]
        _check_correctness(regions, func, envs)


class TestNestedConditionals:
    """Quadrant classifier with 9 regions."""

    def test_region_count(self):
        from decompose import decompose
        r = decompose(_mk_nested())
        assert len(r) == 9, f"Expected 9 regions, got {len(r)}"

    def test_correctness(self):
        from decompose import decompose
        func = _mk_nested()
        regions = decompose(func)
        envs = [{'x': x, 'y': y}
                for x in range(-5, 6) for y in range(-5, 6)]
        _check_correctness(regions, func, envs)


class TestRecursiveFunction:
    """Recursive sum_to with bounded unrolling."""

    def test_has_complete_regions(self):
        from decompose import decompose
        func = _mk_recursive()
        funcs_dict = {func.name: func}
        r = decompose(func, funcs=funcs_dict, unroll_depth=5)
        assert len(r) >= 3, f"Expected >= 3 complete regions, got {len(r)}"

    def test_correctness_within_bound(self):
        from decompose import decompose
        func = _mk_recursive()
        funcs_dict = {func.name: func}
        regions = decompose(func, funcs=funcs_dict, unroll_depth=5)
        envs = [{'n': n} for n in range(-5, 4)]
        _check_correctness(regions, func, envs, funcs=funcs_dict)

    def test_no_unresolved_calls(self):
        """Returned regions must not contain Call nodes in invariants."""
        from decompose import decompose
        func = _mk_recursive()
        funcs_dict = {func.name: func}
        regions = decompose(func, funcs=funcs_dict, unroll_depth=5)

        def has_call(expr):
            if isinstance(expr, Call):
                return True
            if isinstance(expr, BinOp):
                return has_call(expr.left) or has_call(expr.right)
            if isinstance(expr, IfExpr):
                return has_call(expr.then_expr) or has_call(expr.else_expr)
            return False

        for i, r in enumerate(regions):
            assert not has_call(r.invariant), (
                f"Region {i} invariant contains unresolved Call")


class TestCoverageAndDisjointness:
    """Structural properties of the decomposition."""

    def test_simple_coverage(self):
        """Every input must match at least one region."""
        from decompose import decompose
        func = _mk_simple()
        regions = decompose(func)
        for x in range(-100, 300):
            env = {'x': x}
            assert any(_matches(r, env) for r in regions), (
                f"x={x}: no region covers this input")

    def test_simple_disjointness(self):
        """Each input should match at most one region."""
        from decompose import decompose
        func = _mk_simple()
        regions = decompose(func)
        for x in range(-100, 300):
            env = {'x': x}
            n = sum(1 for r in regions if _matches(r, env))
            assert n <= 1, f"x={x}: matches {n} regions (expected <= 1)"

    def test_all_regions_feasible(self):
        """Every returned region must have at least one satisfying input."""
        from decompose import decompose
        func = _mk_simple()
        regions = decompose(func)
        for i, r in enumerate(regions):
            ok = any(_matches(r, {'x': x}) for x in range(-200, 300))
            assert ok, f"Region {i} has no feasible input"

    def test_multi_arg_coverage(self):
        """Coverage for the multi-argument function."""
        from decompose import decompose
        func = _mk_multi()
        regions = decompose(func)
        for x in range(-10, 11):
            for y in range(-10, 11):
                env = {'x': x, 'y': y}
                assert any(_matches(r, env) for r in regions), (
                    f"({x},{y}): no region covers this input")
