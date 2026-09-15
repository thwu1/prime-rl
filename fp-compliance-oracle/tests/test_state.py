"""
Tests for the IEEE 754 floating-point compliance oracle.
Verifies decode, nextafter, totalorder, counterexample, and rounding mode
functionality against the IEEE 754 / C standard Annex F specification.
"""


import subprocess
import struct
import math
import pytest

ORACLE = "/app/fp_oracle"


def setup_module():
    """Compile the oracle binary before running tests."""
    r = subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"Build failed:\n{r.stdout}\n{r.stderr}"


def query(cmd):
    """Send a single command to the oracle and return its stdout."""
    r = subprocess.run(
        [ORACLE],
        input=cmd + "\n",
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, f"Oracle failed on '{cmd}':\n{r.stderr}"
    return r.stdout.strip()


def h2f(h):
    """Hex string -> Python float (native byte order)."""
    return struct.unpack("=d", struct.pack("=Q", int(h, 16)))[0]


def f2b(f):
    """Python float -> uint64 bit pattern."""
    return struct.unpack("=Q", struct.pack("=d", f))[0]


# ── Constants ──────────────────────────────────────────────────────────

POS_ZERO       = "0000000000000000"
NEG_ZERO       = "8000000000000000"
POS_SUBNORM    = "0000000000000001"
NEG_SUBNORM    = "8000000000000001"
POS_ONE        = "3FF0000000000000"
NEG_ONE        = "BFF0000000000000"
POS_TWO        = "4000000000000000"
NEG_TWO        = "C000000000000000"
POS_INF        = "7FF0000000000000"
NEG_INF        = "FFF0000000000000"
QNAN_1         = "7FF8000000000001"   # quiet NaN, payload = 1
SNAN_1         = "7FF0000000000001"   # signaling NaN, payload = 1
DBL_MAX        = "7FEFFFFFFFFFFFFF"
POS_TEN        = "4024000000000000"

EXC_OVERFLOW_INEXACT  = 4 | 16    # 20
EXC_UNDERFLOW_INEXACT = 8 | 16    # 24


# ── DECODE tests ───────────────────────────────────────────────────────

class TestDecode:
    def _decode(self, hexval):
        out = query(f"DECODE {hexval}")
        parts = out.split()
        return {
            "cls": parts[0],
            "sign": int(parts[1]),
            "exp": int(parts[2]),
            "payload": int(parts[3]),
        }

    def test_positive_zero(self):
        d = self._decode(POS_ZERO)
        assert d["cls"] == "POS_ZERO"
        assert d["sign"] == 0

    def test_negative_zero(self):
        d = self._decode(NEG_ZERO)
        assert d["cls"] == "NEG_ZERO", "Must distinguish -0 from +0"
        assert d["sign"] == 1

    def test_positive_subnormal_exponent(self):
        d = self._decode(POS_SUBNORM)
        assert d["cls"] == "POS_SUBNORMAL"
        assert d["exp"] == -1022, (
            "Subnormal unbiased exponent must be 1-1023 = -1022, not -1023"
        )

    def test_negative_subnormal(self):
        d = self._decode(NEG_SUBNORM)
        assert d["cls"] == "NEG_SUBNORMAL"
        assert d["sign"] == 1
        assert d["exp"] == -1022

    def test_normal_one(self):
        d = self._decode(POS_ONE)
        assert d["cls"] == "POS_NORMAL"
        assert d["exp"] == 0  # 1023 - 1023

    def test_normal_negative(self):
        d = self._decode(NEG_ONE)
        assert d["cls"] == "NEG_NORMAL"
        assert d["sign"] == 1

    def test_positive_infinity(self):
        d = self._decode(POS_INF)
        assert d["cls"] == "POS_INFINITY"

    def test_negative_infinity(self):
        d = self._decode(NEG_INF)
        assert d["cls"] == "NEG_INFINITY"

    def test_quiet_nan(self):
        d = self._decode(QNAN_1)
        assert d["cls"] == "QUIET_NAN"
        assert d["payload"] == 1

    def test_signaling_nan(self):
        d = self._decode(SNAN_1)
        assert d["cls"] == "SIGNALING_NAN", (
            "Must check quiet bit to distinguish sNaN from qNaN"
        )
        assert d["payload"] == 1


# ── NEXTAFTER tests ────────────────────────────────────────────────────

class TestNextafter:
    def _na(self, xh, yh):
        out = query(f"NEXTAFTER {xh} {yh}")
        parts = out.split()
        return int(parts[0], 16), int(parts[1])

    def test_increment_one_toward_two(self):
        r, exc = self._na(POS_ONE, POS_TWO)
        assert r == 0x3FF0000000000001
        assert exc == 0

    def test_decrement_two_toward_one(self):
        r, exc = self._na(POS_TWO, POS_ONE)
        assert r == 0x3FFFFFFFFFFFFFFF
        assert exc == 0

    def test_zero_toward_positive(self):
        """nextafter(+0, 1.0) must return smallest positive subnormal."""
        r, exc = self._na(POS_ZERO, POS_ONE)
        assert r == 0x0000000000000001, f"Expected smallest subnormal, got {r:#018x}"
        assert exc == EXC_UNDERFLOW_INEXACT

    def test_zero_toward_negative(self):
        """nextafter(+0, -1.0) must return smallest negative subnormal."""
        r, exc = self._na(POS_ZERO, NEG_ONE)
        assert r == 0x8000000000000001
        assert exc == EXC_UNDERFLOW_INEXACT

    def test_neg_zero_toward_positive(self):
        """nextafter(-0, +1.0) must return smallest positive subnormal."""
        r, exc = self._na(NEG_ZERO, POS_ONE)
        assert r == 0x0000000000000001, f"Expected smallest positive subnormal, got {r:#018x}"
        assert exc == EXC_UNDERFLOW_INEXACT

    def test_positive_zero_toward_negative_zero(self):
        """nextafter(+0, -0) must return -0."""
        r, _ = self._na(POS_ZERO, NEG_ZERO)
        assert r == 0x8000000000000000, "nextafter(+0,-0) should return -0"

    def test_nan_input_x(self):
        """nextafter(sNaN, 1.0) must return a NaN, not step the bit pattern."""
        r, _ = self._na(SNAN_1, POS_ONE)
        exp = (r >> 52) & 0x7FF
        frac = r & ((1 << 52) - 1)
        assert exp == 0x7FF and frac != 0, (
            f"Expected NaN result, got {r:#018x}"
        )

    def test_nan_input_y(self):
        """nextafter(1.0, sNaN) must return a NaN."""
        r, _ = self._na(POS_ONE, SNAN_1)
        exp = (r >> 52) & 0x7FF
        frac = r & ((1 << 52) - 1)
        assert exp == 0x7FF and frac != 0, (
            f"Expected NaN result, got {r:#018x}"
        )

    def test_overflow_to_infinity(self):
        """nextafter(DBL_MAX, +Inf) must return +Inf with overflow+inexact."""
        r, exc = self._na(DBL_MAX, POS_INF)
        assert r == 0x7FF0000000000000
        assert exc == EXC_OVERFLOW_INEXACT

    def test_underflow_to_zero(self):
        """nextafter(smallest_subnorm, 0) must return 0 with underflow+inexact."""
        r, exc = self._na(POS_SUBNORM, POS_ZERO)
        assert r == 0x0000000000000000
        assert exc == EXC_UNDERFLOW_INEXACT

    def test_negative_toward_more_negative(self):
        """nextafter(-1.0, -2.0) must step to next more-negative value."""
        r, exc = self._na(NEG_ONE, NEG_TWO)
        assert r == 0xBFF0000000000001, f"Expected 0xBFF0000000000001, got {r:#018x}"
        assert exc == 0

    def test_negative_step_toward_zero(self):
        """nextafter(-2.0, +0.0) must step toward zero."""
        r, exc = self._na(NEG_TWO, POS_ZERO)
        assert r == 0xBFFFFFFFFFFFFFFF, f"Expected 0xBFFFFFFFFFFFFFFF, got {r:#018x}"
        assert exc == 0


# ── TOTALORDER tests ───────────────────────────────────────────────────

class TestTotalorder:
    def _to(self, ah, bh):
        return int(query(f"TOTALORDER {ah} {bh}"))

    def test_neg_zero_before_pos_zero(self):
        assert self._to(NEG_ZERO, POS_ZERO) == 1, (
            "totalOrder(-0, +0) must be true"
        )

    def test_pos_zero_not_before_neg_zero(self):
        assert self._to(POS_ZERO, NEG_ZERO) == 0, (
            "totalOrder(+0, -0) must be false"
        )

    def test_one_before_two(self):
        assert self._to(POS_ONE, POS_TWO) == 1

    def test_two_not_before_one(self):
        assert self._to(POS_TWO, POS_ONE) == 0

    def test_neg_two_before_neg_one(self):
        assert self._to(NEG_TWO, NEG_ONE) == 1, (
            "totalOrder(-2, -1) must be true (more negative = lesser)"
        )

    def test_neg_one_not_before_neg_two(self):
        assert self._to(NEG_ONE, NEG_TWO) == 0

    def test_neg_inf_before_neg_one(self):
        assert self._to(NEG_INF, NEG_ONE) == 1

    def test_pos_inf_before_pos_nan(self):
        assert self._to(POS_INF, QNAN_1) == 1, (
            "+Inf < +NaN in totalOrder"
        )

    def test_equal_values(self):
        assert self._to(POS_ONE, POS_ONE) == 1, (
            "totalOrder(x, x) must be true"
        )


# ── COUNTEREXAMPLE tests ──────────────────────────────────────────────

class TestCounterexample:
    def _ce(self, tid):
        out = query(f"COUNTEREXAMPLE {tid}")
        return int(out.strip(), 16)

    def test_transform_0_x_minus_x(self):
        """x - x -> 0 is invalid: must find x where x-x != +0."""
        bits = self._ce(0)
        assert bits != 0, "Counterexample must be non-trivial"
        x = h2f(f"{bits:016X}")
        r_bits = f2b(x - x)
        zero_bits = f2b(0.0)
        assert r_bits != zero_bits, (
            f"x-x must not be +0 for counterexample x={bits:#018x}"
        )

    def test_transform_1_x_plus_zero(self):
        """x + 0 -> x is invalid: must find x where (x+0) bits != x bits."""
        bits = self._ce(1)
        x = h2f(f"{bits:016X}")
        r_bits = f2b(x + 0.0)
        assert r_bits != bits, (
            f"x+0 must differ from x for counterexample x={bits:#018x}"
        )

    def test_transform_2_zero_times_x(self):
        """0*x -> 0 is invalid: must find x where 0*x != +0."""
        bits = self._ce(2)
        assert bits != 0, "Counterexample must be non-trivial"
        x = h2f(f"{bits:016X}")
        r_bits = f2b(0.0 * x)
        assert r_bits != f2b(0.0), (
            f"0*x must not be +0 for counterexample x={bits:#018x}"
        )

    def test_transform_3_x_div_x(self):
        """x/x -> 1 is invalid: must find x where x/x != 1."""
        bits = self._ce(3)
        assert bits != 0, "Counterexample must be non-trivial"
        x = h2f(f"{bits:016X}")
        try:
            r_bits = f2b(x / x)
        except ZeroDivisionError:
            return  # x is zero; 0/0 is undefined -> valid counterexample
        assert r_bits != f2b(1.0), (
            f"x/x must not be 1.0 for counterexample x={bits:#018x}"
        )

    def test_transform_4_subtraction_negation(self):
        """x-y vs -(y-x) (y=1.0): must find x where bits differ."""
        bits = self._ce(4)
        x = h2f(f"{bits:016X}")
        y = 1.0
        lhs_bits = f2b(x - y)
        rhs_bits = f2b(-(y - x))
        assert lhs_bits != rhs_bits, (
            f"x-y must differ from -(y-x) for x={bits:#018x}"
        )

    def test_transform_5_negation_vs_subtraction(self):
        """-x vs 0-x: must find x where bits differ."""
        bits = self._ce(5)
        x = h2f(f"{bits:016X}")
        lhs_bits = f2b(-x)
        rhs_bits = f2b(0.0 - x)
        assert lhs_bits != rhs_bits, (
            f"-x must differ from 0-x for x={bits:#018x}"
        )


# ── ROUNDING MODE tests ───────────────────────────────────────────────

class TestRounding:
    def _round(self, ah, bh, op):
        out = query(f"ROUNDING {ah} {bh} {op}")
        parts = out.split()
        return [int(p, 16) for p in parts]

    def test_division_one_over_ten(self):
        """1.0 / 10.0 under all rounding modes."""
        nearest, down, up, zero = self._round(POS_ONE, POS_TEN, 3)

        # For positive 1/10 (not exactly representable):
        # DOWNWARD <= TONEAREST <= UPWARD
        assert down <= nearest <= up
        # TOWARDZERO == DOWNWARD for positive results
        assert zero == down, (
            f"TOWARDZERO ({zero:#018x}) must equal DOWNWARD ({down:#018x}) "
            "for positive result"
        )
        # DOWNWARD and UPWARD must differ (1/10 is not exact)
        assert down != up, "DOWNWARD and UPWARD must differ for inexact result"

        # Exact expected values for 1.0 / 10.0
        assert down == 0x3FB9999999999999, (
            f"DOWNWARD expected 0x3FB9999999999999, got {down:#018x}"
        )
        assert up == 0x3FB999999999999A, (
            f"UPWARD expected 0x3FB999999999999A, got {up:#018x}"
        )

    def test_division_one_over_three(self):
        """1.0 / 3.0 under all rounding modes."""
        three = "4008000000000000"
        nearest, down, up, zero = self._round(POS_ONE, three, 3)

        # 1/3 rounds DOWN in nearest (remainder < 0.5 ULP)
        assert nearest == down, (
            "TONEAREST should equal DOWNWARD for 1/3"
        )
        assert zero == down, (
            "TOWARDZERO should equal DOWNWARD for positive 1/3"
        )
        assert up == down + 1, (
            "UPWARD should be exactly 1 ULP above DOWNWARD for 1/3"
        )

    def test_negative_division(self):
        """(-1.0) / 10.0 under all rounding modes."""
        nearest, down, up, zero = self._round(NEG_ONE, POS_TEN, 3)

        # For negative result:
        # DOWNWARD <= result <= UPWARD (in value, DOWNWARD is more negative)
        # TOWARDZERO == UPWARD for negative results (toward zero = less negative)
        assert zero == up, (
            f"TOWARDZERO ({zero:#018x}) must equal UPWARD ({up:#018x}) "
            "for negative result"
        )
        # DOWNWARD should be more negative (larger magnitude)
        assert down != up
