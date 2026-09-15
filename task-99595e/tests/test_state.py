"""

Tests for bfloat16 arithmetic library IEEE 754 compliance.
Each test class targets a specific IEEE 754 edge case.
"""

import sys
sys.path.insert(0, '/app')

from bf16_arith import (
    bf16_add, bf16_sub, bf16_mul,
    bf16_equal, bf16_less_than, bf16_less_equal, bf16_not_equal,
    is_nan, is_inf, is_zero, is_denormal, sign, exponent, significand,
    pack, negate,
    POS_ZERO, NEG_ZERO, POS_INF, NEG_INF, QNAN, MAX_POS, MAX_NEG,
    RN_EVEN, RN_AWAY, RD, RU, RZ, SIG_MASK,
)


class TestSignOfZero:
    """IEEE 754: x - x = +0 except under RD where it is -0.
    Adding opposite-signed zeros follows the same rule."""

    def test_opposite_zeros_rd_gives_neg_zero(self):
        result = bf16_add(POS_ZERO, NEG_ZERO, RD)
        assert result == NEG_ZERO, f"(+0)+(-0) under RD should be -0, got 0x{result:04X}"

    def test_opposite_zeros_rne_gives_pos_zero(self):
        result = bf16_add(POS_ZERO, NEG_ZERO, RN_EVEN)
        assert result == POS_ZERO

    def test_opposite_zeros_rz_gives_pos_zero(self):
        result = bf16_add(POS_ZERO, NEG_ZERO, RZ)
        assert result == POS_ZERO

    def test_sub_equal_values_rd_gives_neg_zero(self):
        x = pack(0, 127, 0)  # 1.0
        result = bf16_sub(x, x, RD)
        assert result == NEG_ZERO, f"x-x under RD should be -0, got 0x{result:04X}"

    def test_sub_equal_values_rne_gives_pos_zero(self):
        x = pack(0, 127, 0)
        result = bf16_sub(x, x, RN_EVEN)
        assert result == POS_ZERO

    def test_sub_equal_values_ru_gives_pos_zero(self):
        x = pack(0, 130, 0x55)
        result = bf16_sub(x, x, RU)
        assert result == POS_ZERO


class TestOverflowRoundingBehavior:
    """IEEE 754 rounding mode boundary behavior on overflow:
    - RZ: never produces infinity, clamps to max finite
    - RD: cannot produce +inf (positive overflow clamps)
    - RU: cannot produce -inf (negative overflow clamps)
    - RN: overflow produces infinity
    """

    def test_rz_positive_overflow_clamps(self):
        result = bf16_add(MAX_POS, pack(0, 254, 0), RZ)
        assert not is_inf(result), "RZ should never produce infinity from overflow"
        assert result == MAX_POS, f"Expected MAX_POS 0x{MAX_POS:04X}, got 0x{result:04X}"

    def test_rz_negative_overflow_clamps(self):
        result = bf16_add(MAX_NEG, pack(1, 254, 0), RZ)
        assert not is_inf(result), "RZ should never produce infinity from overflow"
        assert result == MAX_NEG

    def test_rd_positive_overflow_clamps(self):
        result = bf16_add(MAX_POS, pack(0, 254, 0), RD)
        assert not is_inf(result), "RD cannot produce +inf"
        assert result == MAX_POS

    def test_rd_negative_overflow_produces_neg_inf(self):
        result = bf16_add(MAX_NEG, pack(1, 254, 0), RD)
        assert result == NEG_INF, "RD can produce -inf"

    def test_ru_negative_overflow_clamps(self):
        result = bf16_add(MAX_NEG, pack(1, 254, 0), RU)
        assert not is_inf(result), "RU cannot produce -inf"
        assert result == MAX_NEG

    def test_ru_positive_overflow_produces_pos_inf(self):
        result = bf16_add(MAX_POS, pack(0, 254, 0), RU)
        assert result == POS_INF, "RU can produce +inf"

    def test_rne_overflow_produces_infinity(self):
        result = bf16_add(MAX_POS, pack(0, 254, 0), RN_EVEN)
        assert is_inf(result)

    def test_mul_rz_overflow_clamps(self):
        a = pack(0, 200, 0x7F)
        b = pack(0, 200, 0x7F)
        result = bf16_mul(a, b, RZ)
        assert not is_inf(result), "RZ mul should clamp on overflow"


class TestZeroTimesInfinity:
    """IEEE 754: 0 * infinity is an invalid operation, must return qNaN."""

    def test_pos_zero_times_pos_inf(self):
        result = bf16_mul(POS_ZERO, POS_INF, RN_EVEN)
        assert is_nan(result), f"0*inf should be NaN, got 0x{result:04X}"

    def test_neg_zero_times_pos_inf(self):
        result = bf16_mul(NEG_ZERO, POS_INF, RN_EVEN)
        assert is_nan(result)

    def test_pos_zero_times_neg_inf(self):
        result = bf16_mul(POS_ZERO, NEG_INF, RZ)
        assert is_nan(result)

    def test_pos_inf_times_pos_zero(self):
        result = bf16_mul(POS_INF, POS_ZERO, RD)
        assert is_nan(result)

    def test_neg_inf_times_neg_zero(self):
        result = bf16_mul(NEG_INF, NEG_ZERO, RU)
        assert is_nan(result)


class TestInfinityPlusMinusInfinity:
    """IEEE 754: inf + (-inf) and (-inf) + inf are indeterminate, return qNaN."""

    def test_pos_inf_plus_neg_inf(self):
        result = bf16_add(POS_INF, NEG_INF, RN_EVEN)
        assert is_nan(result), f"inf+(-inf) should be NaN, got 0x{result:04X}"

    def test_neg_inf_plus_pos_inf(self):
        result = bf16_add(NEG_INF, POS_INF, RN_EVEN)
        assert is_nan(result)

    def test_inf_minus_inf(self):
        result = bf16_sub(POS_INF, POS_INF, RZ)
        assert is_nan(result)

    def test_neg_inf_minus_neg_inf(self):
        result = bf16_sub(NEG_INF, NEG_INF, RD)
        assert is_nan(result)

    def test_same_sign_inf_addition_ok(self):
        assert bf16_add(POS_INF, POS_INF, RN_EVEN) == POS_INF
        assert bf16_add(NEG_INF, NEG_INF, RN_EVEN) == NEG_INF


class TestDenormalResults:
    """IEEE 754 gradual underflow: subtraction of close values near the minimum
    normal should produce denormal results, not flush to zero."""

    def test_smallest_denormal_from_subtraction(self):
        a = pack(0, 1, 1)   # smallest normal + 1 ulp
        b = pack(0, 1, 0)   # smallest positive normal
        result = bf16_sub(a, b, RZ)
        expected = pack(0, 0, 1)  # smallest positive denormal
        assert result == expected, (
            f"Expected denormal 0x{expected:04X}, got 0x{result:04X}"
        )

    def test_larger_denormal_from_subtraction(self):
        a = pack(0, 1, 0x10)
        b = pack(0, 1, 0)
        result = bf16_sub(a, b, RZ)
        expected = pack(0, 0, 0x10)
        assert result == expected, (
            f"Expected denormal 0x{expected:04X}, got 0x{result:04X}"
        )

    def test_negative_denormal_result(self):
        a = pack(1, 1, 0x08)
        b = pack(1, 1, 0)
        result = bf16_sub(a, b, RZ)
        expected = pack(1, 0, 0x08)
        assert result == expected, (
            f"Expected negative denormal 0x{expected:04X}, got 0x{result:04X}"
        )

    def test_denormal_is_not_zero(self):
        a = pack(0, 1, 0x01)
        b = pack(0, 1, 0x00)
        result = bf16_sub(a, b, RZ)
        assert not is_zero(result), "Denormal result should not be zero"
        assert is_denormal(result), "Result should be denormal"

    def test_half_denormal_range(self):
        a = pack(0, 1, 0x40)  # sig=0x40
        b = pack(0, 1, 0)
        result = bf16_sub(a, b, RZ)
        expected = pack(0, 0, 0x40)
        assert result == expected


class TestNanComparisons:
    """IEEE 754: NaN is unordered with everything including itself.
    All comparisons except != must return False when a NaN is involved."""

    def test_nan_not_less_than_number(self):
        x = pack(0, 127, 0)  # 1.0
        assert not bf16_less_than(QNAN, x), "NaN < 1.0 should be False"

    def test_number_not_less_than_nan(self):
        x = pack(0, 127, 0)
        assert not bf16_less_than(x, QNAN), "1.0 < NaN should be False"

    def test_nan_not_less_than_nan(self):
        assert not bf16_less_than(QNAN, QNAN), "NaN < NaN should be False"

    def test_nan_not_less_than_neg_inf(self):
        assert not bf16_less_than(QNAN, NEG_INF)

    def test_neg_inf_not_less_than_nan(self):
        assert not bf16_less_than(NEG_INF, QNAN)

    def test_nan_not_equal_nan(self):
        assert not bf16_equal(QNAN, QNAN)

    def test_nan_not_equal_is_true(self):
        assert bf16_not_equal(QNAN, QNAN)

    def test_different_nan_payloads(self):
        nan1 = pack(0, 0xFF, 0x01)
        nan2 = pack(0, 0xFF, 0x3F)
        assert not bf16_less_than(nan1, nan2)
        assert not bf16_less_than(nan2, nan1)


class TestRneTieBreaking:
    """IEEE 754 RN_EVEN: on exact ties (equidistant between two representable
    values), round to the value with even LSB in the significand."""

    def test_mul_tie_rounds_up_when_lsb_odd(self):
        # 129/128 * 192/128 = 24768/16384 = 1.51171875
        # Nearest: sig=0x41 (1.5078125) and sig=0x42 (1.515625)
        # Equidistant: 0x41 has odd LSB -> round UP to 0x42
        a = pack(0, 127, 1)   # sig=0x01, ma=129
        b = pack(0, 127, 64)  # sig=0x40, ma=192
        result = bf16_mul(a, b, RN_EVEN)
        expected = pack(0, 127, 0x42)
        assert result == expected, (
            f"RNE tie with odd LSB should round up: "
            f"expected 0x{expected:04X}, got 0x{result:04X}"
        )

    def test_mul_tie_stays_when_lsb_even(self):
        # 130/128 * 160/128 = 20800/16384 = 1.26953125 (not a tie, actually)
        # Let's verify: 130*160=20800, lower 7 bits: 20800>>7=162, 162&0x7F=0x22
        # guard=(20800>>6)&1=1, round=(20800>>5)&1=0, sticky=20800&0x1F=0
        # tie: LSB of 0x22 = 0 (even) -> do NOT round up
        a = pack(0, 127, 2)   # sig=0x02, ma=130
        b = pack(0, 127, 32)  # sig=0x20, ma=160
        result = bf16_mul(a, b, RN_EVEN)
        expected = pack(0, 127, 0x22)
        assert result == expected, (
            f"RNE tie with even LSB should not round: "
            f"expected 0x{expected:04X}, got 0x{result:04X}"
        )

    def test_rne_vs_rna_differ_on_even_tie(self):
        # Same tie case as above but with RNA: should round UP
        a = pack(0, 127, 2)
        b = pack(0, 127, 32)
        result_rna = bf16_mul(a, b, RN_AWAY)
        result_rne = bf16_mul(a, b, RN_EVEN)
        # RNA always rounds up on tie, RNE rounds to even
        assert result_rna == pack(0, 127, 0x23), "RNA should round up on tie"
        # The two should differ for this tie case (even LSB)
        assert result_rne != result_rna, "RNE and RNA should differ on even-LSB tie"


class TestBasicArithmetic:
    """Sanity checks for basic operations (not targeting specific bugs)."""

    def test_one_plus_one(self):
        one = pack(0, 127, 0)
        result = bf16_add(one, one, RN_EVEN)
        assert result == pack(0, 128, 0), "1.0 + 1.0 should be 2.0"

    def test_one_times_one(self):
        one = pack(0, 127, 0)
        result = bf16_mul(one, one, RN_EVEN)
        assert result == pack(0, 127, 0), "1.0 * 1.0 should be 1.0"

    def test_subtraction_basic(self):
        two = pack(0, 128, 0)
        one = pack(0, 127, 0)
        result = bf16_sub(two, one, RN_EVEN)
        # 2.0 - 1.0 = 1.0
        assert result == one

    def test_negative_addition(self):
        neg_one = pack(1, 127, 0)
        neg_two = pack(1, 128, 0)
        result = bf16_add(neg_one, neg_one, RN_EVEN)
        assert result == neg_two, "-1 + -1 = -2"

    def test_nan_propagates_add(self):
        result = bf16_add(QNAN, pack(0, 127, 0), RN_EVEN)
        assert is_nan(result)

    def test_nan_propagates_mul(self):
        result = bf16_mul(QNAN, pack(0, 127, 0), RN_EVEN)
        assert is_nan(result)

    def test_inf_times_finite(self):
        result = bf16_mul(POS_INF, pack(0, 127, 0), RN_EVEN)
        assert result == POS_INF

    def test_zero_plus_x(self):
        x = pack(0, 130, 0x55)
        assert bf16_add(POS_ZERO, x, RN_EVEN) == x
        assert bf16_add(x, POS_ZERO, RN_EVEN) == x

    def test_equality_zero_signs(self):
        assert bf16_equal(POS_ZERO, NEG_ZERO)
        assert bf16_equal(NEG_ZERO, POS_ZERO)
