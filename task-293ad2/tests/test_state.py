"""
Tests for the Sea-of-Nodes IR optimizer.

Validates optimization quality, semantic preservation, and correct
native execution via C code generation and gcc compilation.
"""


import sys
sys.path.insert(0, '/opt/son_ir')
sys.path.insert(0, '/app')

from ir import Graph, Node, Op, DataType

I1  = DataType.I1
I8  = DataType.I8
I16 = DataType.I16
I32 = DataType.I32
I64 = DataType.I64


def _opt(g: Graph) -> Graph:
    """Import and run the optimizer."""
    from optimizer import optimize
    optimize(g)
    return g


# ===================================================================
# Constant folding
# ===================================================================

class TestConstantFolding:
    def test_add(self):
        g = Graph([])
        g.set_result(g.add(g.iconst(I32, 7), g.iconst(I32, 5)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 12

    def test_sub(self):
        g = Graph([])
        g.set_result(g.sub(g.iconst(I32, 10), g.iconst(I32, 3)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 7

    def test_mul(self):
        g = Graph([])
        g.set_result(g.mul(g.iconst(I32, 6), g.iconst(I32, 7)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 42

    def test_chain(self):
        """(3 + 5) * (10 - 2) = 64"""
        g = Graph([])
        a = g.add(g.iconst(I32, 3), g.iconst(I32, 5))
        b = g.sub(g.iconst(I32, 10), g.iconst(I32, 2))
        g.set_result(g.mul(a, b))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 64

    def test_i8_overflow(self):
        """i8: 200 + 100 = 300 & 0xFF = 44"""
        g = Graph([])
        g.set_result(g.add(g.iconst(I8, 200), g.iconst(I8, 100)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 44

    def test_signed_div(self):
        """-7 /s -2 = 3  (truncation toward zero)"""
        g = Graph([])
        a = g.iconst(I32, I32.truncate(-7))
        b = g.iconst(I32, I32.truncate(-2))
        g.set_result(g.sdiv(a, b))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 3

    def test_comparison(self):
        """5 < 3 is false -> 0"""
        g = Graph([])
        g.set_result(g.cmp_slt(g.iconst(I32, 5), g.iconst(I32, 3)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0

    def test_neg_const(self):
        """neg(5) in i32 = 0xFFFFFFFB"""
        g = Graph([])
        g.set_result(g.neg(g.iconst(I32, 5)))
        _opt(g)
        assert g.result.is_const
        assert g.result.const_val == I32.truncate(-5)

    def test_not_const(self):
        """not(0xFF00) in i16 = 0x00FF"""
        g = Graph([])
        g.set_result(g.not_(g.iconst(I16, 0xFF00)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0x00FF


# ===================================================================
# Identity rules  (x op identity_element -> x)
# ===================================================================

class TestIdentity:
    def test_add_zero(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.add(x, g.iconst(I32, 0)))
        _opt(g)
        assert g.result is x

    def test_sub_zero(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.sub(x, g.iconst(I32, 0)))
        _opt(g)
        assert g.result is x

    def test_mul_one(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.mul(x, g.iconst(I32, 1)))
        _opt(g)
        assert g.result is x

    def test_and_allones(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.and_(x, g.iconst(I32, 0xFFFFFFFF)))
        _opt(g)
        assert g.result is x

    def test_or_zero(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.or_(x, g.iconst(I32, 0)))
        _opt(g)
        assert g.result is x

    def test_xor_zero(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.xor(x, g.iconst(I32, 0)))
        _opt(g)
        assert g.result is x

    def test_shl_zero(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.shl(x, g.iconst(I32, 0)))
        _opt(g)
        assert g.result is x

    def test_lshr_zero(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.lshr(x, g.iconst(I32, 0)))
        _opt(g)
        assert g.result is x

    def test_udiv_one(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.udiv(x, g.iconst(I32, 1)))
        _opt(g)
        assert g.result is x

    def test_sdiv_one(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.sdiv(x, g.iconst(I32, 1)))
        _opt(g)
        assert g.result is x


# ===================================================================
# Annihilator / self-op rules
# ===================================================================

class TestAlgebraic:
    def test_mul_zero(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.mul(x, g.iconst(I32, 0)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0

    def test_and_zero(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.and_(x, g.iconst(I32, 0)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0

    def test_sub_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.sub(x, x))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0

    def test_xor_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.xor(x, x))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0

    def test_and_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.and_(x, x))
        _opt(g)
        assert g.result is x

    def test_or_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.or_(x, x))
        _opt(g)
        assert g.result is x

    def test_or_allones(self):
        g = Graph([I16]); x = g.params[0]
        g.set_result(g.or_(x, g.iconst(I16, 0xFFFF)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0xFFFF

    def test_umod_one(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.umod(x, g.iconst(I32, 1)))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0


# ===================================================================
# Unary double-inverse
# ===================================================================

class TestUnary:
    def test_double_neg(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.neg(g.neg(x)))
        _opt(g)
        assert g.result is x

    def test_double_not(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.not_(g.not_(x)))
        _opt(g)
        assert g.result is x


# ===================================================================
# Strength reduction
# ===================================================================

class TestStrengthReduction:
    def test_mul_pow2(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.mul(x, g.iconst(I32, 8)))
        _opt(g)
        assert g.result.op == Op.SHL
        assert g.result.inputs[1].is_const
        assert g.result.inputs[1].const_val == 3

    def test_udiv_pow2(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.udiv(x, g.iconst(I32, 4)))
        _opt(g)
        assert g.result.op == Op.LSHR
        assert g.result.inputs[1].const_val == 2

    def test_umod_pow2(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.umod(x, g.iconst(I32, 16)))
        _opt(g)
        assert g.result.op == Op.AND
        assert g.result.inputs[1].const_val == 15

    def test_mul_pow2_large(self):
        """x * 256 -> x << 8"""
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.mul(x, g.iconst(I32, 256)))
        _opt(g)
        assert g.result.op == Op.SHL
        assert g.result.inputs[1].const_val == 8


# ===================================================================
# Comparison simplification
# ===================================================================

class TestComparison:
    def test_eq_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.cmp_eq(x, x))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 1

    def test_ne_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.cmp_ne(x, x))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0

    def test_slt_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.cmp_slt(x, x))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0

    def test_sle_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.cmp_sle(x, x))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 1

    def test_ult_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.cmp_ult(x, x))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0

    def test_ule_self(self):
        g = Graph([I32]); x = g.params[0]
        g.set_result(g.cmp_ule(x, x))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 1


# ===================================================================
# Select simplification
# ===================================================================

class TestSelect:
    def test_const_true(self):
        g = Graph([I32, I32])
        a, b = g.params
        g.set_result(g.select(g.iconst(I1, 1), a, b))
        _opt(g)
        assert g.result is a

    def test_const_false(self):
        g = Graph([I32, I32])
        a, b = g.params
        g.set_result(g.select(g.iconst(I1, 0), a, b))
        _opt(g)
        assert g.result is b

    def test_same_arms(self):
        g = Graph([I32, I1])
        x, c = g.params
        g.set_result(g.select(c, x, x))
        _opt(g)
        assert g.result is x


# ===================================================================
# GVN / CSE
# ===================================================================

class TestGVN:
    def test_dedup(self):
        """Two identical (x + y) nodes should be merged."""
        g = Graph([I32, I32])
        x, y = g.params
        a1 = g.add(x, y)
        a2 = g.add(x, y)
        g.set_result(g.add(a1, a2))
        _opt(g)
        # After GVN, both inputs to the outer add point to the same node
        assert g.result.inputs[0] is g.result.inputs[1]

    def test_dedup_enables_sub_zero(self):
        """(x+y) - (x+y) -> 0  after GVN merges the two (x+y) nodes."""
        g = Graph([I32, I32])
        x, y = g.params
        a1 = g.add(x, y)
        a2 = g.add(x, y)
        g.set_result(g.sub(a1, a2))
        _opt(g)
        assert g.result.is_const and g.result.const_val == 0

    def test_commutative(self):
        """add(x, y) and add(y, x) should be merged."""
        g = Graph([I32, I32])
        x, y = g.params
        a1 = g.add(x, y)
        a2 = g.add(y, x)
        g.set_result(g.mul(a1, a2))
        _opt(g)
        assert g.result.inputs[0] is g.result.inputs[1]


# ===================================================================
# Cast simplification
# ===================================================================

class TestCast:
    def test_trunc_zext_roundtrip(self):
        """trunc_i8(zext_i32(x:i8)) -> x"""
        g = Graph([I8]); x = g.params[0]
        g.set_result(g.trunc(g.zext(x, I32), I8))
        _opt(g)
        assert g.result is x

    def test_trunc_sext_roundtrip(self):
        """trunc_i8(sext_i32(x:i8)) -> x"""
        g = Graph([I8]); x = g.params[0]
        g.set_result(g.trunc(g.sext(x, I32), I8))
        _opt(g)
        assert g.result is x

    def test_const_cast(self):
        """sext_i32(iconst.i8 200) -> iconst.i32 of sign-extended value"""
        g = Graph([])
        g.set_result(g.sext(g.iconst(I8, 200), I32))
        _opt(g)
        assert g.result.is_const
        # 200 in i8 is -56 signed, sign-extended to i32
        assert g.result.const_val == I32.truncate(-56)


# ===================================================================
# Multi-step optimizations (require iterative convergence)
# ===================================================================

class TestMultiStep:
    def test_chain_identities(self):
        """((x + 0) * 1) ^ 0 -> x  (3 rounds of simplification)"""
        g = Graph([I32]); x = g.params[0]
        a = g.add(x, g.iconst(I32, 0))
        b = g.mul(a, g.iconst(I32, 1))
        c = g.xor(b, g.iconst(I32, 0))
        g.set_result(c)
        _opt(g)
        assert g.result is x

    def test_cmp_then_select(self):
        """select(cmp_eq(x, x), a, b) -> a  (cmp folds, then select folds)"""
        g = Graph([I32, I32, I32])
        x, a, b = g.params
        cond = g.cmp_eq(x, x)
        g.set_result(g.select(cond, a, b))
        _opt(g)
        assert g.result is a

    def test_node_count_reduced(self):
        """A redundant graph with many identities should shrink significantly."""
        g = Graph([I32, I32])
        x, y = g.params
        # Build: (x+0) + (y*1) + (x^0) + (y|0) = 2x + 2y
        a = g.add(x, g.iconst(I32, 0))        # x
        b = g.mul(y, g.iconst(I32, 1))          # y
        c = g.xor(x, g.iconst(I32, 0))          # x
        d = g.or_(y, g.iconst(I32, 0))           # y
        g.set_result(g.add(g.add(a, b), g.add(c, d)))
        before = g.op_count()
        _opt(g)
        after = g.op_count()
        assert after < before, f"Expected fewer ops after optimization: {after} >= {before}"
        # The graph should have at most 3 add nodes (a+b, c+d, sum)
        # After identity + GVN: (x+y) + (x+y) with just 2 adds
        assert after <= 3

    def test_strength_reduction_preserves_semantics(self):
        """Mul-by-power-of-2 -> shl must produce the same results."""
        import random
        random.seed(12345)
        g = Graph([I32])
        x = g.params[0]
        g.set_result(g.mul(x, g.iconst(I32, 32)))
        inputs = [random.randint(0, 2**32 - 1) for _ in range(200)]
        expected = [g.evaluate([v]) for v in inputs]
        _opt(g)
        actual = [g.evaluate([v]) for v in inputs]
        assert expected == actual


# ===================================================================
# Semantic preservation (fuzz-style)
# ===================================================================

class TestSemanticPreservation:
    def _check(self, g, inputs_list):
        expected = [g.evaluate(inp) for inp in inputs_list]
        _opt(g)
        actual = [g.evaluate(inp) for inp in inputs_list]
        assert expected == actual, "Optimization changed program semantics"

    def test_complex_expression(self):
        """Build a complex expression, verify output unchanged after opt."""
        import random
        random.seed(42)
        g = Graph([I32, I32])
        x, y = g.params
        xp3 = g.add(x, g.iconst(I32, 3))
        ym1 = g.sub(y, g.iconst(I32, 1))
        prod1 = g.mul(xp3, ym1)
        prod2 = g.mul(x, y)
        s = g.add(prod1, prod2)
        band = g.and_(x, y)
        xp3_dup = g.add(x, g.iconst(I32, 3))   # duplicate for GVN
        bor = g.or_(band, xp3_dup)
        g.set_result(g.xor(s, bor))
        inputs = [[random.randint(0, 2**32 - 1) for _ in range(2)]
                   for _ in range(200)]
        self._check(g, inputs)

    def test_mixed_types(self):
        """Expression mixing i8 and i32 via casts."""
        import random
        random.seed(99)
        g = Graph([I8, I8])
        a, b = g.params
        wa = g.zext(a, I32)
        wb = g.zext(b, I32)
        prod = g.mul(wa, wb)
        lo = g.trunc(prod, I8)
        g.set_result(lo)
        inputs = [[random.randint(0, 255), random.randint(0, 255)]
                   for _ in range(200)]
        self._check(g, inputs)

    def test_signed_ops(self):
        """Signed division and comparison chain."""
        import random
        random.seed(77)
        g = Graph([I32, I32])
        x, y = g.params
        one = g.iconst(I32, 1)
        # Avoid div-by-zero by using (y | 1)
        safe_y = g.or_(y, one)
        q = g.sdiv(x, safe_y)
        r = g.smod(x, safe_y)
        # Verify: q*safe_y + r should equal x
        check = g.add(g.mul(q, safe_y), r)
        g.set_result(check)
        inputs = [[random.randint(0, 2**32 - 1), random.randint(0, 2**32 - 1)]
                   for _ in range(200)]
        self._check(g, inputs)

    def test_shifts_and_masks(self):
        """Shift + mask expression."""
        import random
        random.seed(55)
        g = Graph([I32])
        x = g.params[0]
        # Extract bits [8:16] of x:  (x >> 8) & 0xFF
        shifted = g.lshr(x, g.iconst(I32, 8))
        masked = g.and_(shifted, g.iconst(I32, 0xFF))
        # Reconstruct: masked << 8
        reconstructed = g.shl(masked, g.iconst(I32, 8))
        g.set_result(reconstructed)
        inputs = [[random.randint(0, 2**32 - 1)] for _ in range(200)]
        self._check(g, inputs)


# ===================================================================
# Native execution via gcc (end-to-end verification)
# ===================================================================

class TestNativeExecution:
    """Verify optimizer correctness by compiling optimized IR to C and
    running natively with gcc.  These tests exercise the full
    Python -> C -> binary pipeline."""

    def _verify_native(self, g, inputs_list):
        """Evaluate with Python, optimize, compile to C, run, compare."""
        expected = [g.evaluate(inp) for inp in inputs_list]
        _opt(g)
        from codegen import compile_and_run
        actual = compile_and_run(g, inputs_list)
        assert actual == expected, (
            f"Native execution mismatch:\n  expected={expected[:5]}...\n"
            f"  actual  ={actual[:5]}..."
        )

    def test_arithmetic_native(self):
        """Arithmetic chain verified via native C execution."""
        import random
        random.seed(3001)
        g = Graph([I32, I32])
        x, y = g.params
        g.set_result(g.add(g.mul(x, y), g.sub(x, g.iconst(I32, 7))))
        inputs = [[random.randint(0, 2**32 - 1) for _ in range(2)]
                   for _ in range(100)]
        self._verify_native(g, inputs)

    def test_bitwise_native(self):
        """Bitwise expression verified via native C execution."""
        import random
        random.seed(3002)
        g = Graph([I32, I32])
        x, y = g.params
        g.set_result(g.xor(g.and_(x, y), g.or_(x, g.iconst(I32, 0xFF))))
        inputs = [[random.randint(0, 2**32 - 1) for _ in range(2)]
                   for _ in range(100)]
        self._verify_native(g, inputs)

    def test_signed_division_native(self):
        """Signed division verified via native C execution."""
        import random
        random.seed(3003)
        g = Graph([I32, I32])
        x, y = g.params
        safe_y = g.or_(y, g.iconst(I32, 1))
        q = g.sdiv(x, safe_y)
        r = g.smod(x, safe_y)
        g.set_result(g.add(g.mul(q, safe_y), r))
        inputs = [[random.randint(0, 2**32 - 1), random.randint(0, 2**32 - 1)]
                   for _ in range(100)]
        self._verify_native(g, inputs)

    def test_mixed_width_casts_native(self):
        """i8 -> i32 casts and truncation verified via native C execution."""
        import random
        random.seed(3004)
        g = Graph([I8, I8])
        a, b = g.params
        wa = g.zext(a, I32)
        wb = g.sext(b, I32)
        diff = g.sub(wa, wb)
        lo = g.trunc(diff, I8)
        g.set_result(lo)
        inputs = [[random.randint(0, 255), random.randint(0, 255)]
                   for _ in range(100)]
        self._verify_native(g, inputs)

    def test_strength_reduction_native(self):
        """Mul-by-power-of-2 verified via native C execution after opt."""
        import random
        random.seed(3005)
        g = Graph([I32])
        x = g.params[0]
        g.set_result(g.mul(x, g.iconst(I32, 64)))
        inputs = [[random.randint(0, 2**32 - 1)] for _ in range(100)]
        self._verify_native(g, inputs)

    def test_constant_fold_native(self):
        """Fully constant expression verified via native C execution."""
        g = Graph([])
        a = g.add(g.iconst(I32, 100), g.iconst(I32, 200))
        b = g.mul(a, g.iconst(I32, 3))
        g.set_result(b)
        self._verify_native(g, [[]])

    def test_gvn_then_fold_native(self):
        """GVN dedup enabling x-x=0, verified via native C execution."""
        import random
        random.seed(3007)
        g = Graph([I32, I32])
        x, y = g.params
        a1 = g.add(x, y)
        a2 = g.add(x, y)
        # (x+y) - (x+y) should fold to 0 after GVN
        g.set_result(g.add(g.sub(a1, a2), x))
        inputs = [[random.randint(0, 2**32 - 1) for _ in range(2)]
                   for _ in range(100)]
        self._verify_native(g, inputs)

    def test_comparison_select_native(self):
        """Comparison + select chain verified via native C execution."""
        import random
        random.seed(3008)
        g = Graph([I32, I32])
        x, y = g.params
        cond = g.cmp_ult(x, y)
        min_val = g.select(cond, x, y)
        g.set_result(min_val)
        inputs = [[random.randint(0, 2**32 - 1) for _ in range(2)]
                   for _ in range(100)]
        self._verify_native(g, inputs)
