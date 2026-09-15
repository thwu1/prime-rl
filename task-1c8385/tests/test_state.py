"""Comprehensive tests for bfloat16 arithmetic library."""


import sys
sys.path.insert(0, '/app')

import math
import pytest
from bf16 import (
    bf16_unpack, bf16_pack, bf16_classify, bf16_to_float,
    bf16_from_float, bf16_add, bf16_mul,
)

# ---- Raw-value constants ----
ZERO  = 0x0000  # +0
NZERO = 0x8000  # -0
ONE   = 0x3F80  # 1.0
NONE_ = 0xBF80  # -1.0
TWO   = 0x4000  # 2.0
HALF  = 0x3F00  # 0.5
INF   = 0x7F80  # +Inf
NINF  = 0xFF80  # -Inf
NAN   = 0x7FC0  # canonical qNaN
MAXN  = 0x7F7F  # max positive normal: (255/128)*2^127
NMAXN = 0xFF7F  # most negative normal: -(255/128)*2^127
MINN  = 0x0080  # min positive normal: 2^(-126)
MINS  = 0x0001  # min positive subnormal: 2^(-133)
MAXS  = 0x007F  # max positive subnormal: 127*2^(-133)


# ================================================================
# Pack / Unpack
# ================================================================

class TestUnpackPack:
    def test_roundtrip_special_values(self):
        for raw in [ZERO, NZERO, ONE, NONE_, TWO, HALF, INF, NINF,
                     NAN, MAXN, MINN, MINS, MAXS, 0x8001]:
            s, e, m = bf16_unpack(raw)
            assert bf16_pack(s, e, m) == raw, f"roundtrip failed for 0x{raw:04X}"

    def test_unpack_one(self):
        assert bf16_unpack(ONE) == (0, 127, 0)

    def test_unpack_neg_one(self):
        assert bf16_unpack(NONE_) == (1, 127, 0)

    def test_unpack_max_normal(self):
        s, e, m = bf16_unpack(MAXN)
        assert (s, e, m) == (0, 254, 127)

    def test_unpack_nan(self):
        s, e, m = bf16_unpack(NAN)
        assert e == 255 and m != 0


# ================================================================
# Classification
# ================================================================

class TestClassify:
    def test_zero(self):
        assert bf16_classify(ZERO) == "zero"
        assert bf16_classify(NZERO) == "zero"

    def test_subnormal(self):
        assert bf16_classify(MINS) == "subnormal"
        assert bf16_classify(MAXS) == "subnormal"
        assert bf16_classify(0x8001) == "subnormal"

    def test_normal(self):
        assert bf16_classify(ONE) == "normal"
        assert bf16_classify(MAXN) == "normal"
        assert bf16_classify(MINN) == "normal"

    def test_infinity(self):
        assert bf16_classify(INF) == "infinity"
        assert bf16_classify(NINF) == "infinity"

    def test_nan(self):
        assert bf16_classify(NAN) == "nan"
        assert bf16_classify(0x7F81) == "nan"


# ================================================================
# Conversion: bf16 -> float
# ================================================================

class TestToFloat:
    def test_zero(self):
        assert bf16_to_float(ZERO) == 0.0
        v = bf16_to_float(NZERO)
        assert v == 0.0 and math.copysign(1.0, v) == -1.0

    def test_one(self):
        assert bf16_to_float(ONE) == 1.0
        assert bf16_to_float(NONE_) == -1.0

    def test_two(self):
        assert bf16_to_float(TWO) == 2.0

    def test_half(self):
        assert bf16_to_float(HALF) == 0.5

    def test_inf(self):
        assert bf16_to_float(INF) == float('inf')
        assert bf16_to_float(NINF) == float('-inf')

    def test_nan(self):
        assert math.isnan(bf16_to_float(NAN))

    def test_min_subnormal(self):
        assert bf16_to_float(MINS) == 2.0 ** (-133)

    def test_max_subnormal(self):
        assert bf16_to_float(MAXS) == 127 * 2.0 ** (-133)

    def test_max_normal(self):
        expected = (255.0 / 128.0) * (2.0 ** 127)
        assert bf16_to_float(MAXN) == expected

    def test_three(self):
        # 3.0 = 0x4040: exp=128, man=64 -> (128+64)*2^(128-134) = 192/64 = 3.0
        assert bf16_to_float(0x4040) == 3.0


# ================================================================
# Conversion: float -> bf16
# ================================================================

class TestFromFloatBasic:
    def test_exact_values(self):
        assert bf16_from_float(1.0) == ONE
        assert bf16_from_float(-1.0) == NONE_
        assert bf16_from_float(0.0) == ZERO
        assert bf16_from_float(2.0) == TWO
        assert bf16_from_float(0.5) == HALF
        assert bf16_from_float(3.0) == 0x4040

    def test_negative_zero(self):
        assert bf16_from_float(-0.0) == NZERO

    def test_inf(self):
        assert bf16_from_float(float('inf')) == INF
        assert bf16_from_float(float('-inf')) == NINF

    def test_nan(self):
        assert bf16_from_float(float('nan')) == NAN


class TestFromFloatRounding:
    def test_tie_odd_lsb(self):
        # 1 + 3/256 = 1.01171875: midpoint between 0x3F81(man=1,odd) and 0x3F82
        v = 1.01171875
        assert bf16_from_float(v, "RNE") == 0x3F82  # tie -> even (round up)
        assert bf16_from_float(v, "RNA") == 0x3F82  # tie -> away
        assert bf16_from_float(v, "RZ")  == 0x3F81  # truncate
        assert bf16_from_float(v, "RU")  == 0x3F82  # positive -> up
        assert bf16_from_float(v, "RD")  == 0x3F81  # positive -> truncate

    def test_tie_even_lsb(self):
        # 1 + 5/256 = 1.01953125: midpoint between 0x3F82(man=2,even) and 0x3F83
        v = 1.01953125
        assert bf16_from_float(v, "RNE") == 0x3F82  # tie -> even (keep)
        assert bf16_from_float(v, "RNA") == 0x3F83  # tie -> away
        assert bf16_from_float(v, "RZ")  == 0x3F82  # truncate
        assert bf16_from_float(v, "RU")  == 0x3F83  # positive -> up
        assert bf16_from_float(v, "RD")  == 0x3F82  # positive -> truncate

    def test_negative_tie(self):
        # -1.01171875: midpoint between 0xBF81(man=1,odd) and 0xBF82
        v = -1.01171875
        assert bf16_from_float(v, "RNE") == 0xBF82  # tie -> even
        assert bf16_from_float(v, "RNA") == 0xBF82  # tie -> away
        assert bf16_from_float(v, "RZ")  == 0xBF81  # toward zero
        assert bf16_from_float(v, "RU")  == 0xBF81  # toward +inf = smaller mag
        assert bf16_from_float(v, "RD")  == 0xBF82  # toward -inf = larger mag


# ================================================================
# Addition: special values
# ================================================================

class TestAddSpecial:
    def test_nan_propagation(self):
        assert bf16_add(NAN, ONE) == NAN
        assert bf16_add(ONE, NAN) == NAN
        assert bf16_add(NAN, NAN) == NAN
        assert bf16_add(NAN, INF) == NAN

    def test_inf_same_sign(self):
        assert bf16_add(INF, INF) == INF
        assert bf16_add(NINF, NINF) == NINF

    def test_inf_opposite_sign(self):
        assert bf16_add(INF, NINF) == NAN
        assert bf16_add(NINF, INF) == NAN

    def test_inf_plus_finite(self):
        assert bf16_add(INF, ONE) == INF
        assert bf16_add(ONE, INF) == INF
        assert bf16_add(NINF, ONE) == NINF

    def test_zero_plus_zero_same_sign(self):
        assert bf16_add(ZERO, ZERO) == ZERO
        assert bf16_add(NZERO, NZERO) == NZERO

    def test_zero_plus_zero_opposite_sign(self):
        assert bf16_add(ZERO, NZERO, "RNE") == ZERO
        assert bf16_add(ZERO, NZERO, "RZ")  == ZERO
        assert bf16_add(ZERO, NZERO, "RD")  == NZERO

    def test_zero_plus_nonzero(self):
        assert bf16_add(ZERO, ONE) == ONE
        assert bf16_add(ONE, ZERO) == ONE
        assert bf16_add(ZERO, MINS) == MINS


# ================================================================
# Addition: basic arithmetic
# ================================================================

class TestAddBasic:
    def test_one_plus_one(self):
        assert bf16_add(ONE, ONE) == TWO

    def test_one_plus_neg_one(self):
        assert bf16_add(ONE, NONE_) == ZERO

    def test_cancellation_to_neg_zero(self):
        assert bf16_add(ONE, NONE_, "RD") == NZERO

    def test_cancellation_to_subnormal(self):
        # (1+1/128)*2^(-126) - 2^(-126) = (1/128)*2^(-126) = 2^(-133) = min_sub
        assert bf16_add(0x0081, 0x8080) == MINS

    def test_large_cancellation(self):
        # 1.0078125 - 1.0 = 0.0078125 = 2^(-7) = 0x3C00
        assert bf16_add(0x3F81, NONE_) == 0x3C00


# ================================================================
# Addition: rounding modes
# ================================================================

class TestAddRounding:
    def test_midpoint_even_lsb(self):
        # 1.0 + 2^(-8) = 1 + 1/256: midpoint between 0x3F80(man=0,even) and 0x3F81
        # 0x3B80 = 2^(-8)
        a, b = ONE, 0x3B80
        assert bf16_add(a, b, "RNE") == 0x3F80  # tie -> even (keep 0)
        assert bf16_add(a, b, "RNA") == 0x3F81  # tie -> away
        assert bf16_add(a, b, "RZ")  == 0x3F80
        assert bf16_add(a, b, "RU")  == 0x3F81
        assert bf16_add(a, b, "RD")  == 0x3F80

    def test_above_midpoint(self):
        # 1.0 + 1.5*2^(-8) = 1 + 3/512: above midpoint
        # 0x3BC0 = 1.5*2^(-8)
        a, b = ONE, 0x3BC0
        assert bf16_add(a, b, "RNE") == 0x3F81
        assert bf16_add(a, b, "RNA") == 0x3F81
        assert bf16_add(a, b, "RZ")  == 0x3F80
        assert bf16_add(a, b, "RD")  == 0x3F80


# ================================================================
# Addition: overflow
# ================================================================

class TestAddOverflow:
    def test_positive_overflow(self):
        assert bf16_add(MAXN, MAXN, "RNE") == INF
        assert bf16_add(MAXN, MAXN, "RZ")  == MAXN
        assert bf16_add(MAXN, MAXN, "RU")  == INF
        assert bf16_add(MAXN, MAXN, "RD")  == MAXN

    def test_negative_overflow(self):
        assert bf16_add(NMAXN, NMAXN, "RNE") == NINF
        assert bf16_add(NMAXN, NMAXN, "RZ")  == NMAXN
        assert bf16_add(NMAXN, NMAXN, "RU")  == NMAXN  # toward +inf -> clamp
        assert bf16_add(NMAXN, NMAXN, "RD")  == NINF   # toward -inf -> -inf


# ================================================================
# Addition: subnormals
# ================================================================

class TestAddSubnormal:
    def test_add_two_subnormals(self):
        assert bf16_add(MINS, MINS) == 0x0002

    def test_subnormal_to_normal(self):
        # 64*2^(-133) + 64*2^(-133) = 128*2^(-133) = 2^(-126) = min_normal
        assert bf16_add(0x0040, 0x0040) == MINN

    def test_subnormal_subtraction(self):
        # 3*2^(-133) - 1*2^(-133) = 2*2^(-133)
        assert bf16_add(0x0003, 0x8001) == 0x0002

    def test_subnormal_cancellation_to_zero(self):
        assert bf16_add(0x0003, 0x8003, "RNE") == ZERO
        assert bf16_add(0x0003, 0x8003, "RD")  == NZERO


# ================================================================
# Multiplication: special values
# ================================================================

class TestMulSpecial:
    def test_nan_propagation(self):
        assert bf16_mul(NAN, ONE) == NAN
        assert bf16_mul(ONE, NAN) == NAN
        assert bf16_mul(NAN, NAN) == NAN

    def test_inf_times_zero_is_nan(self):
        assert bf16_mul(INF, ZERO) == NAN
        assert bf16_mul(ZERO, INF) == NAN
        assert bf16_mul(NINF, ZERO) == NAN
        assert bf16_mul(ZERO, NINF) == NAN

    def test_inf_times_finite(self):
        assert bf16_mul(INF, ONE)   == INF
        assert bf16_mul(INF, NONE_) == NINF
        assert bf16_mul(NINF, NONE_) == INF

    def test_zero_sign(self):
        assert bf16_mul(ZERO, ONE)   == ZERO   # +0 * +1 = +0
        assert bf16_mul(NZERO, ONE)  == NZERO  # -0 * +1 = -0
        assert bf16_mul(ZERO, NONE_) == NZERO  # +0 * -1 = -0
        assert bf16_mul(NZERO, NONE_) == ZERO  # -0 * -1 = +0


# ================================================================
# Multiplication: basic
# ================================================================

class TestMulBasic:
    def test_one_times_one(self):
        assert bf16_mul(ONE, ONE) == ONE

    def test_two_times_two(self):
        assert bf16_mul(TWO, TWO) == 0x4080  # 4.0

    def test_half_times_two(self):
        assert bf16_mul(HALF, TWO) == ONE

    def test_neg_times_neg(self):
        assert bf16_mul(NONE_, NONE_) == ONE

    def test_neg_times_pos(self):
        assert bf16_mul(NONE_, TWO) == 0xC000  # -2.0


# ================================================================
# Multiplication: rounding modes
# ================================================================

class TestMulRounding:
    def test_midpoint_odd_lsb(self):
        # 1.0078125 * 1.5: sig=129*192=24768, mantissa=65(odd), exact midpoint
        a, b = 0x3F81, 0x3FC0
        assert bf16_mul(a, b, "RNE") == 0x3FC2  # tie -> even (66)
        assert bf16_mul(a, b, "RNA") == 0x3FC2  # tie -> away (66)
        assert bf16_mul(a, b, "RZ")  == 0x3FC1  # truncate (65)
        assert bf16_mul(a, b, "RU")  == 0x3FC2  # positive -> up
        assert bf16_mul(a, b, "RD")  == 0x3FC1  # positive -> truncate

    def test_midpoint_even_lsb(self):
        # 1.015625 * 1.25: sig=130*160=20800, mantissa=34(even), exact midpoint
        a, b = 0x3F82, 0x3FA0
        assert bf16_mul(a, b, "RNE") == 0x3FA2  # tie -> even (keep 34)
        assert bf16_mul(a, b, "RNA") == 0x3FA3  # tie -> away (35)
        assert bf16_mul(a, b, "RZ")  == 0x3FA2
        assert bf16_mul(a, b, "RU")  == 0x3FA3
        assert bf16_mul(a, b, "RD")  == 0x3FA2


# ================================================================
# Multiplication: overflow
# ================================================================

class TestMulOverflow:
    def test_positive_overflow(self):
        assert bf16_mul(MAXN, TWO, "RNE") == INF
        assert bf16_mul(MAXN, TWO, "RZ")  == MAXN

    def test_negative_overflow(self):
        assert bf16_mul(NMAXN, TWO, "RNE") == NINF
        assert bf16_mul(NMAXN, TWO, "RZ")  == NMAXN
        assert bf16_mul(NMAXN, TWO, "RU")  == NMAXN  # toward +inf -> clamp
        assert bf16_mul(NMAXN, TWO, "RD")  == NINF    # toward -inf


# ================================================================
# Multiplication: underflow
# ================================================================

class TestMulUnderflow:
    def test_deep_underflow_to_zero(self):
        # 2^(-126) * 2^(-133) = 2^(-259) -> zero under RNE
        assert bf16_mul(MINN, MINS, "RNE") == ZERO

    def test_deep_underflow_rounds_up_under_ru(self):
        # Same product under RU: positive inexact -> min subnormal
        assert bf16_mul(MINN, MINS, "RU") == MINS

    def test_normal_to_subnormal(self):
        # 2^(-126) * 0.5 = 2^(-127) -> subnormal, man=64
        assert bf16_mul(MINN, HALF) == 0x0040

    def test_midpoint_at_zero_boundary(self):
        # 2^(-67) * 2^(-67) = 2^(-134) = exactly 0.5 * min_subnormal
        a = bf16_pack(0, 60, 0)  # 2^(-67)
        assert bf16_mul(a, a, "RNE") == ZERO  # tie -> even (0 is even)
        assert bf16_mul(a, a, "RNA") == MINS  # tie -> away
        assert bf16_mul(a, a, "RU")  == MINS  # positive -> up
        assert bf16_mul(a, a, "RD")  == ZERO  # positive -> truncate
