"""
Tests for Sea of Nodes IR JIT compiler.

Verifies that jit_compile produces native executables whose results
match the reference evaluator for all IR node types and edge cases.
"""

import sys
import types
sys.path.insert(0, '/app')

import pytest
from son_ir.nodes import Node, NodeType, DataType, I1, I8, I16, I32, I64
from son_ir.graph import Graph
from son_ir.evaluator import evaluate
from son_ir.jit import jit_compile


# =============================================================
# Interface checks
# =============================================================

class TestInterface:
    def test_returns_native_callable(self):
        """jit_compile must return native code, not a Python function."""
        g = Graph()
        result = g.add(g.iconst(10, I32), g.iconst(20, I32))
        func = jit_compile(result, 0)
        assert callable(func)
        assert not isinstance(func, (types.FunctionType, types.MethodType,
                                     types.LambdaType)), \
            "Expected native machine code callable, not a Python function"

    def test_independent_of_evaluator(self):
        """JIT must produce standalone native code, not delegate to evaluator."""
        import son_ir.evaluator as ev_mod
        original = ev_mod.evaluate
        ev_mod.evaluate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blocked"))
        try:
            g = Graph()
            result = g.add(g.iconst(7, I32), g.iconst(35, I32))
            func = jit_compile(result, 0)
            assert func() == 42
        finally:
            ev_mod.evaluate = original


# =============================================================
# Constants and parameters
# =============================================================

class TestLeafNodes:
    def test_iconst_i32(self):
        g = Graph()
        func = jit_compile(g.iconst(0xDEADBEEF, I32), 0)
        assert func() == 0xDEADBEEF

    def test_iconst_i64(self):
        g = Graph()
        func = jit_compile(g.iconst(0x123456789ABCDEF0, I64), 0)
        assert func() == 0x123456789ABCDEF0

    def test_iconst_i8(self):
        g = Graph()
        func = jit_compile(g.iconst(0xFF, I8), 0)
        assert func() == 0xFF

    def test_param_passthrough(self):
        g = Graph()
        func = jit_compile(g.param(0, I32), 1)
        assert func(42) == 42
        assert func(0xFFFFFFFF) == 0xFFFFFFFF

    def test_param_masking(self):
        """Parameters wider than the type must be masked."""
        g = Graph()
        func = jit_compile(g.param(0, I8), 1)
        assert func(0x1FF) == 0xFF

    def test_multiple_params(self):
        g = Graph()
        x = g.param(0, I64)
        y = g.param(1, I64)
        z = g.param(2, I64)
        w = g.param(3, I64)
        result = g.add(g.add(x, y), g.add(z, w))
        func = jit_compile(result, 4)
        assert func(10, 20, 30, 40) == 100


# =============================================================
# Arithmetic operations
# =============================================================

class TestArithmetic:
    def test_add(self):
        g = Graph()
        result = g.add(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(100, 200) == 300

    def test_add_overflow(self):
        g = Graph()
        result = g.add(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(0xFFFFFFFF, 1) == 0

    def test_sub(self):
        g = Graph()
        result = g.sub(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(100, 30) == 70

    def test_sub_underflow(self):
        g = Graph()
        result = g.sub(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(0, 1) == 0xFFFFFFFF

    def test_mul(self):
        g = Graph()
        result = g.mul(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(7, 6) == 42

    def test_neg(self):
        g = Graph()
        result = g.neg(g.param(0, I32))
        func = jit_compile(result, 1)
        assert func(1) == 0xFFFFFFFF
        assert func(0) == 0


# =============================================================
# Division
# =============================================================

class TestDivision:
    def test_udiv(self):
        g = Graph()
        result = g.udiv(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(100, 7) == 14
        assert func(0, 5) == 0

    def test_udiv_by_zero(self):
        g = Graph()
        result = g.udiv(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(42, 0) == 0

    def test_sdiv_negative(self):
        g = Graph()
        result = g.sdiv(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        # -10 / 3 = -3 (truncate toward zero)
        neg10 = 0xFFFFFFF6  # -10 as u32
        expected = evaluate(result, {0: neg10, 1: 3})
        assert func(neg10, 3) == expected

    def test_sdiv_by_zero(self):
        g = Graph()
        result = g.sdiv(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(42, 0) == 0


# =============================================================
# Bitwise operations
# =============================================================

class TestBitwise:
    def test_and(self):
        g = Graph()
        result = g.and_(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(0xFF00, 0x0FF0) == 0x0F00

    def test_or(self):
        g = Graph()
        result = g.or_(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(0xFF00, 0x00FF) == 0xFFFF

    def test_xor(self):
        g = Graph()
        result = g.xor(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(0xFF, 0xFF) == 0
        assert func(0xAA, 0x55) == 0xFF

    def test_not(self):
        g = Graph()
        result = g.not_(g.param(0, I8))
        func = jit_compile(result, 1)
        assert func(0x00) == 0xFF
        assert func(0xAA) == 0x55


# =============================================================
# Shifts
# =============================================================

class TestShifts:
    def test_shl(self):
        g = Graph()
        result = g.shl(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(1, 4) == 16
        assert func(0xFF, 8) == 0xFF00

    def test_shl_overflow(self):
        """Shift by >= type width must produce 0."""
        g = Graph()
        result = g.shl(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(1, 32) == 0
        assert func(0xFFFFFFFF, 33) == 0

    def test_shr(self):
        g = Graph()
        result = g.shr(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(256, 4) == 16
        assert func(0x80000000, 31) == 1

    def test_shr_overflow(self):
        g = Graph()
        result = g.shr(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(0xFFFFFFFF, 32) == 0

    def test_sar_negative(self):
        g = Graph()
        result = g.sar(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        neg8 = 0xFFFFFFF8  # -8 as u32
        expected = evaluate(result, {0: neg8, 1: 2})
        assert func(neg8, 2) == expected

    def test_sar_overflow(self):
        """SAR by >= width: all-ones if negative, zero if positive."""
        g = Graph()
        result = g.sar(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        neg1 = 0xFFFFFFFF
        expected = evaluate(result, {0: neg1, 1: 32})
        assert func(neg1, 32) == expected
        assert func(1, 32) == 0


# =============================================================
# Comparisons
# =============================================================

class TestComparisons:
    def test_cmp_eq(self):
        g = Graph()
        result = g.cmp_eq(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(42, 42) == 1
        assert func(42, 43) == 0

    def test_cmp_ne(self):
        g = Graph()
        result = g.cmp_ne(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(42, 43) == 1
        assert func(42, 42) == 0

    def test_cmp_slt_signed(self):
        """Signed less-than must handle negative numbers correctly."""
        g = Graph()
        result = g.cmp_slt(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        neg1 = 0xFFFFFFFF  # -1 as u32
        assert func(neg1, 0) == 1   # -1 < 0 is true
        assert func(0, neg1) == 0   # 0 < -1 is false
        assert func(5, 10) == 1

    def test_cmp_slt_int_min(self):
        g = Graph()
        result = g.cmp_slt(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        int_min = 0x80000000
        assert func(int_min, 1) == 1   # INT_MIN < 1

    def test_cmp_sle(self):
        g = Graph()
        result = g.cmp_sle(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(5, 5) == 1
        neg1 = 0xFFFFFFFF
        assert func(neg1, 0) == 1

    def test_cmp_ult(self):
        g = Graph()
        result = g.cmp_ult(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(5, 10) == 1
        assert func(10, 5) == 0
        # Unsigned: 0xFFFFFFFF > 0
        assert func(0xFFFFFFFF, 0) == 0

    def test_cmp_ule(self):
        g = Graph()
        result = g.cmp_ule(g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(5, 5) == 1
        assert func(5, 6) == 1
        assert func(6, 5) == 0


# =============================================================
# Select
# =============================================================

class TestSelect:
    def test_select_true(self):
        g = Graph()
        cond = g.iconst(1, I1)
        result = g.select(cond, g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(42, 99) == 42

    def test_select_false(self):
        g = Graph()
        cond = g.iconst(0, I1)
        result = g.select(cond, g.param(0, I32), g.param(1, I32))
        func = jit_compile(result, 2)
        assert func(42, 99) == 99

    def test_select_dynamic(self):
        g = Graph()
        x = g.param(0, I32)
        y = g.param(1, I32)
        cond = g.cmp_ult(x, y)
        result = g.select(cond, x, y)  # min(x, y)
        func = jit_compile(result, 2)
        assert func(3, 7) == 3
        assert func(7, 3) == 3


# =============================================================
# Width conversions
# =============================================================

class TestWidthConversions:
    def test_zext(self):
        g = Graph()
        result = g.zext(g.param(0, I8), I32)
        func = jit_compile(result, 1)
        assert func(0xFF) == 0xFF
        assert func(0x80) == 0x80

    def test_sext(self):
        g = Graph()
        result = g.sext(g.param(0, I8), I32)
        func = jit_compile(result, 1)
        assert func(0x80) == 0xFFFFFF80  # sign-extend -128
        assert func(0x7F) == 0x7F

    def test_trunc(self):
        g = Graph()
        result = g.trunc(g.param(0, I32), I8)
        func = jit_compile(result, 1)
        assert func(0x1234) == 0x34

    def test_trunc_zext_roundtrip(self):
        g = Graph()
        x = g.param(0, I32)
        t = g.trunc(x, I8)
        z = g.zext(t, I32)
        func = jit_compile(z, 1)
        assert func(0xABCD) == 0xCD

    def test_sext_i16_to_i64(self):
        g = Graph()
        result = g.sext(g.param(0, I16), I64)
        func = jit_compile(result, 1)
        assert func(0x8000) == 0xFFFFFFFFFFFF8000
        assert func(0x7FFF) == 0x7FFF


# =============================================================
# Complex / multi-level expressions
# =============================================================

class TestComplex:
    def test_nested_arithmetic(self):
        """(a + b) * (a - b) for multiple inputs."""
        g = Graph()
        a = g.param(0, I32)
        b = g.param(1, I32)
        result = g.mul(g.add(a, b), g.sub(a, b))
        func = jit_compile(result, 2)
        for av, bv in [(10, 3), (100, 50), (0, 0), (1, 1)]:
            expected = evaluate(result, {0: av, 1: bv})
            assert func(av, bv) == expected, f"Failed for a={av}, b={bv}"

    def test_dag_sharing(self):
        """DAG nodes referenced by multiple consumers."""
        g = Graph()
        x = g.param(0, I32)
        doubled = g.add(x, x)
        result = g.mul(doubled, doubled)  # (2x)^2
        func = jit_compile(result, 1)
        assert func(5) == 100
        assert func(10) == 400

    def test_mixed_widths(self):
        """Expression mixing different bit widths."""
        g = Graph()
        x = g.param(0, I32)
        narrow = g.trunc(x, I8)
        wide = g.zext(narrow, I32)
        result = g.add(x, wide)
        func = jit_compile(result, 1)
        expected = evaluate(result, {0: 0x1234})
        assert func(0x1234) == expected

    def test_comparison_driven_select(self):
        """Clamp value: max(min(x, 100), 0)."""
        g = Graph()
        x = g.param(0, I32)
        hundred = g.iconst(100, I32)
        zero = g.iconst(0, I32)
        lt100 = g.cmp_ult(x, hundred)
        capped = g.select(lt100, x, hundred)
        gt0 = g.cmp_slt(zero, capped)
        result = g.select(gt0, capped, zero)
        func = jit_compile(result, 1)
        expected = evaluate(result, {0: 50})
        assert func(50) == expected
        expected2 = evaluate(result, {0: 200})
        assert func(200) == expected2

    def test_five_params(self):
        """Expression using 5 parameters to stress register allocation."""
        g = Graph()
        a, b, c, d, e = [g.param(i, I64) for i in range(5)]
        ab = g.add(a, b)
        cd = g.mul(c, d)
        abcd = g.sub(ab, cd)
        result = g.xor(abcd, e)
        func = jit_compile(result, 5)
        vals = (10, 20, 3, 4, 0xFF)
        expected = evaluate(result, dict(enumerate(vals)))
        assert func(*vals) == expected

    def test_evaluator_parity_comprehensive(self):
        """Cross-check various operations against the evaluator."""
        test_cases = []

        g1 = Graph()
        x = g1.param(0, I32)
        test_cases.append((g1.and_(x, g1.iconst(0xFF, I32)), 1, [(0x1234,)]))

        g2 = Graph()
        x = g2.param(0, I32)
        test_cases.append((g2.or_(x, g2.iconst(0xFF00, I32)), 1, [(0x00FF,)]))

        g3 = Graph()
        x = g3.param(0, I32)
        y = g3.param(1, I32)
        shl_node = g3.shl(x, y)
        test_cases.append((shl_node, 2, [(1, 0), (1, 31), (0xFF, 4)]))

        g4 = Graph()
        x = g4.param(0, I32)
        test_cases.append((g4.neg(x), 1, [(0,), (1,), (0x80000000,)]))

        for root, np, inputs_list in test_cases:
            func = jit_compile(root, np)
            for inputs in inputs_list:
                expected = evaluate(root, dict(enumerate(inputs)))
                actual = func(*inputs)
                assert actual == expected, \
                    f"Mismatch: inputs={inputs}, expected={expected}, got={actual}"
