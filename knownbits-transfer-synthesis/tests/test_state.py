"""
Exhaustive soundness and precision tests for KnownBits transfer functions.
"""

import sys
import os
import inspect
import random
import textwrap

sys.path.insert(0, '/app')

from knownbits import (
    KnownBits, top, constant, meet,
    verify_transfer_soundness, measure_precision,
    BINARY_OPS, UNARY_OPS,
    get_min_unsigned, get_max_unsigned,
)
from transfers import TRANSFER_FUNCTIONS


# ============================================================
# Anti-cheat: ensure transfer functions don't enumerate
# ============================================================

class TestAntiCheat:
    """Verify transfer functions don't call concrete_set or enumerate values."""

    def test_no_concrete_set_calls(self):
        """Transfer functions must not call concrete_set()."""
        import transfers
        source = inspect.getsource(transfers)
        # Remove comments
        lines = source.split('\n')
        code_lines = [l for l in lines if not l.strip().startswith('#')]
        code = '\n'.join(code_lines)
        assert 'concrete_set' not in code, \
            "Transfer functions must not call concrete_set() — they must use O(1)/O(width) bit reasoning"

    def test_no_itertools_product_on_values(self):
        """Transfer functions must not enumerate concrete values."""
        import transfers
        source = inspect.getsource(transfers)
        lines = source.split('\n')
        code_lines = [l for l in lines if not l.strip().startswith('#')]
        code = '\n'.join(code_lines)
        # Check for patterns that suggest brute-force enumeration
        assert 'itertools.product' not in code, \
            "Transfer functions must not use itertools.product to enumerate concrete values"

    def test_no_range_enumeration(self):
        """Transfer functions must not iterate over range(2**width) or similar."""
        import transfers
        source = inspect.getsource(transfers)
        lines = source.split('\n')
        code_lines = [l for l in lines if not l.strip().startswith('#')]
        code = '\n'.join(code_lines)
        assert 'range(1 <<' not in code and 'range(2**' not in code, \
            "Transfer functions must not enumerate all possible values via range(2**width)"


# ============================================================
# Soundness tests at 4-bit width (exhaustive)
# ============================================================

class TestSoundness4Bit:
    """Exhaustive soundness verification at 4-bit width."""

    def _check_soundness(self, op_name):
        arity, fn = TRANSFER_FUNCTIONS[op_name]
        is_unary = (arity == 'unary')
        sound, cex = verify_transfer_soundness(op_name, fn, width=4, is_unary=is_unary)
        if not sound:
            if is_unary:
                msg = (f"UNSOUND: {op_name} transfer function\n"
                       f"  Input: {cex['input']}\n"
                       f"  Concrete input: {cex['concrete_input']}\n"
                       f"  Concrete result: {cex['concrete_result']}\n"
                       f"  Abstract result: {cex['abstract_result']} (does not contain concrete result)")
            else:
                msg = (f"UNSOUND: {op_name} transfer function\n"
                       f"  LHS: {cex['lhs']}, RHS: {cex['rhs']}\n"
                       f"  Concrete: {cex['concrete_lhs']} op {cex['concrete_rhs']} = {cex['concrete_result']}\n"
                       f"  Abstract result: {cex['abstract_result']} (does not contain concrete result)")
            assert False, msg

    def test_and_soundness(self):
        self._check_soundness('and')

    def test_or_soundness(self):
        self._check_soundness('or')

    def test_xor_soundness(self):
        self._check_soundness('xor')

    def test_shl_soundness(self):
        self._check_soundness('shl')

    def test_lshr_soundness(self):
        self._check_soundness('lshr')

    def test_ashr_soundness(self):
        self._check_soundness('ashr')

    def test_add_soundness(self):
        self._check_soundness('add')

    def test_sub_soundness(self):
        self._check_soundness('sub')

    def test_mul_soundness(self):
        self._check_soundness('mul')

    def test_neg_soundness(self):
        self._check_soundness('neg')

    def test_not_soundness(self):
        self._check_soundness('not')


# ============================================================
# Soundness spot-checks at 8-bit width (sampled)
# ============================================================

class TestSoundness8BitSampled:
    """Spot-check soundness at 8-bit width on random KnownBits inputs."""

    def _sample_knownbits(self, width, rng):
        full = (1 << width) - 1
        # Random masks, ensuring no conflict
        mask = rng.randint(0, full)
        vals = rng.randint(0, full) & mask
        zero_mask = mask & ~vals
        one_mask = mask & vals
        return KnownBits(width, zero_mask, one_mask)

    def _check_soundness_sampled(self, op_name, num_samples=2000):
        arity, fn = TRANSFER_FUNCTIONS[op_name]
        is_unary = (arity == 'unary')
        width = 8
        rng = random.Random(42 + hash(op_name))

        if is_unary:
            concrete_fn = UNARY_OPS[op_name]
            for _ in range(num_samples):
                kb1 = self._sample_knownbits(width, rng)
                result_kb = fn(kb1)
                for v1 in kb1.concrete_set():
                    cv = concrete_fn(v1, width)
                    if cv is not None:
                        assert result_kb.contains(cv), \
                            f"UNSOUND at 8-bit: {op_name}({kb1}) -> {result_kb}, " \
                            f"but {op_name}({v1}) = {cv} not contained"
        else:
            concrete_fn = BINARY_OPS[op_name]
            for _ in range(num_samples):
                kb1 = self._sample_knownbits(width, rng)
                kb2 = self._sample_knownbits(width, rng)
                result_kb = fn(kb1, kb2)
                for v1 in kb1.concrete_set():
                    for v2 in kb2.concrete_set():
                        cv = concrete_fn(v1, v2, width)
                        if cv is not None:
                            assert result_kb.contains(cv), \
                                f"UNSOUND at 8-bit: {op_name}({kb1}, {kb2}) -> {result_kb}, " \
                                f"but {op_name}({v1}, {v2}) = {cv} not contained"

    def test_and_8bit(self):
        self._check_soundness_sampled('and')

    def test_or_8bit(self):
        self._check_soundness_sampled('or')

    def test_xor_8bit(self):
        self._check_soundness_sampled('xor')

    def test_shl_8bit(self):
        self._check_soundness_sampled('shl')

    def test_lshr_8bit(self):
        self._check_soundness_sampled('lshr')

    def test_ashr_8bit(self):
        self._check_soundness_sampled('ashr')

    def test_add_8bit(self):
        self._check_soundness_sampled('add')

    def test_sub_8bit(self):
        self._check_soundness_sampled('sub')

    def test_mul_8bit(self):
        self._check_soundness_sampled('mul')

    def test_neg_8bit(self):
        self._check_soundness_sampled('neg')

    def test_not_8bit(self):
        self._check_soundness_sampled('not')


# ============================================================
# Precision tests at 4-bit width
# ============================================================

class TestPrecision:
    """Measure precision of transfer functions against optimal."""

    def _get_precision(self, op_name):
        arity, fn = TRANSFER_FUNCTIONS[op_name]
        is_unary = (arity == 'unary')
        return measure_precision(op_name, fn, width=4, is_unary=is_unary)

    # Bitwise ops should be near-perfect (100% is achievable)
    def test_and_precision(self):
        p = self._get_precision('and')
        assert p >= 0.95, f"AND precision {p:.3f} < 0.95 — optimal is achievable for bitwise ops"

    def test_or_precision(self):
        p = self._get_precision('or')
        assert p >= 0.95, f"OR precision {p:.3f} < 0.95 — optimal is achievable for bitwise ops"

    def test_xor_precision(self):
        p = self._get_precision('xor')
        assert p >= 0.95, f"XOR precision {p:.3f} < 0.95 — optimal is achievable for bitwise ops"

    def test_not_precision(self):
        p = self._get_precision('not')
        assert p >= 0.95, f"NOT precision {p:.3f} < 0.95 — optimal is achievable"

    # Shift ops should be high precision when shift amount is known
    def test_shl_precision(self):
        p = self._get_precision('shl')
        assert p >= 0.70, f"SHL precision {p:.3f} < 0.70"

    def test_lshr_precision(self):
        p = self._get_precision('lshr')
        assert p >= 0.70, f"LSHR precision {p:.3f} < 0.70"

    def test_ashr_precision(self):
        p = self._get_precision('ashr')
        assert p >= 0.65, f"ASHR precision {p:.3f} < 0.65"

    # Arithmetic ops — harder, lower threshold
    def test_add_precision(self):
        p = self._get_precision('add')
        assert p >= 0.50, f"ADD precision {p:.3f} < 0.50"

    def test_sub_precision(self):
        p = self._get_precision('sub')
        assert p >= 0.45, f"SUB precision {p:.3f} < 0.45"

    def test_mul_precision(self):
        p = self._get_precision('mul')
        assert p >= 0.30, f"MUL precision {p:.3f} < 0.30"

    def test_neg_precision(self):
        p = self._get_precision('neg')
        assert p >= 0.50, f"NEG precision {p:.3f} < 0.50"

    # Overall average precision
    def test_average_precision(self):
        ops = ['and', 'or', 'xor', 'shl', 'lshr', 'ashr', 'add', 'sub', 'mul', 'neg', 'not']
        precisions = {}
        for op in ops:
            precisions[op] = self._get_precision(op)

        avg = sum(precisions.values()) / len(precisions)
        detail = ', '.join(f"{op}={p:.3f}" for op, p in precisions.items())
        assert avg >= 0.60, \
            f"Average precision {avg:.3f} < 0.60. Detail: {detail}"


# ============================================================
# Specific correctness tests for known edge cases
# ============================================================

class TestEdgeCases:
    """Test specific edge cases that are easy to get wrong."""

    def test_add_known_constants(self):
        """Adding two known constants should produce a known constant."""
        fn = TRANSFER_FUNCTIONS['add'][1]
        a = constant(4, 3)   # 0011
        b = constant(4, 5)   # 0101
        result = fn(a, b)
        # 3 + 5 = 8 = 1000
        assert result.contains(8), f"add(3,5)=8 not in {result}"
        assert result == constant(4, 8), f"add of constants should be exact: got {result}"

    def test_sub_known_constants(self):
        fn = TRANSFER_FUNCTIONS['sub'][1]
        a = constant(4, 7)
        b = constant(4, 3)
        result = fn(a, b)
        assert result.contains(4), f"sub(7,3)=4 not in {result}"
        assert result == constant(4, 4), f"sub of constants should be exact: got {result}"

    def test_mul_known_constants(self):
        fn = TRANSFER_FUNCTIONS['mul'][1]
        a = constant(4, 3)
        b = constant(4, 5)
        result = fn(a, b)
        # 3 * 5 = 15 = 1111
        assert result.contains(15), f"mul(3,5)=15 not in {result}"

    def test_shl_known_amount(self):
        """Shifting by a known amount should shift the masks."""
        fn = TRANSFER_FUNCTIONS['shl'][1]
        a = KnownBits(4, 0b1000, 0b0011)  # ??11 -> known low bits
        b = constant(4, 1)  # shift left by 1
        result = fn(a, b)
        # 0011 << 1 = 0110, ?011 << 1 = ?110, bottom bit becomes known-zero
        assert result.zero_mask & 0b0001, f"SHL by 1 should make bit 0 known-zero, got {result}"

    def test_lshr_known_amount(self):
        fn = TRANSFER_FUNCTIONS['lshr'][1]
        a = KnownBits(4, 0b0001, 0b1100)  # 11?0
        b = constant(4, 1)
        result = fn(a, b)
        # top bit should become known-zero after logical right shift
        assert result.zero_mask & 0b1000, f"LSHR by 1 should make MSB known-zero, got {result}"

    def test_and_partial_known(self):
        fn = TRANSFER_FUNCTIONS['and'][1]
        a = KnownBits(4, 0b1100, 0b0011)  # 0011
        b = KnownBits(4, 0b0000, 0b0000)  # ????
        result = fn(a, b)
        # bits 2,3 of a are known-zero, so result bits 2,3 must be known-zero
        assert (result.zero_mask & 0b1100) == 0b1100, \
            f"AND with known-zero bits should propagate: got {result}"

    def test_or_partial_known(self):
        fn = TRANSFER_FUNCTIONS['or'][1]
        a = KnownBits(4, 0b1100, 0b0011)  # 0011
        b = KnownBits(4, 0b0000, 0b0000)  # ????
        result = fn(a, b)
        # bits 0,1 of a are known-one, so result bits 0,1 must be known-one
        assert (result.one_mask & 0b0011) == 0b0011, \
            f"OR with known-one bits should propagate: got {result}"

    def test_xor_same_bits(self):
        fn = TRANSFER_FUNCTIONS['xor'][1]
        a = KnownBits(4, 0b1010, 0b0101)  # 0101
        b = KnownBits(4, 0b1010, 0b0101)  # 0101
        result = fn(a, b)
        # XOR of identical known values = 0
        assert result == constant(4, 0), f"XOR of identical values should be 0, got {result}"

    def test_not_known_bits(self):
        fn = TRANSFER_FUNCTIONS['not'][1]
        a = KnownBits(4, 0b1010, 0b0101)  # 0101
        result = fn(a)
        expected = KnownBits(4, 0b0101, 0b1010)  # 1010
        assert result == expected, f"NOT of 0101 should be 1010, got {result}"

    def test_neg_zero(self):
        fn = TRANSFER_FUNCTIONS['neg'][1]
        a = constant(4, 0)
        result = fn(a)
        assert result.contains(0), f"neg(0) = 0 not in {result}"

    def test_ashr_negative(self):
        """Arithmetic right shift of negative number should fill with 1s."""
        fn = TRANSFER_FUNCTIONS['ashr'][1]
        a = KnownBits(4, 0b0000, 0b1000)  # 1??? (sign bit known-one)
        b = constant(4, 2)  # shift by 2
        result = fn(a, b)
        # After ashr by 2, top 3 bits should all be known-one (sign-extended)
        assert (result.one_mask & 0b1110) == 0b1110, \
            f"ASHR of negative by 2 should sign-extend top 3 bits, got {result}"

    def test_add_overflow_wrap(self):
        """Test that add handles modular arithmetic correctly."""
        fn = TRANSFER_FUNCTIONS['add'][1]
        a = constant(4, 15)  # 1111
        b = constant(4, 1)   # 0001
        result = fn(a, b)
        # 15 + 1 = 16 = 0 (mod 16)
        assert result.contains(0), f"add(15,1) should wrap to 0, got {result}"
