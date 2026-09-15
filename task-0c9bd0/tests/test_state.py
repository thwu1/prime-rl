
"""
Comprehensive IEEE 754 compliance tests for FP8 E4M3 arithmetic.
Tests the C shared library via ctypes and the Verilog adder via iverilog.

Format: 1 sign bit, 4 exponent bits, 3 mantissa bits, bias=7.
"""

import subprocess
import sys
import os
import math
import pytest

# ============================================================
# Build the C shared library
# ============================================================

@pytest.fixture(scope="session", autouse=True)
def build_library():
    """Build libfp8.so before running tests."""
    result = subprocess.run(
        ["make", "-C", "/app", "clean"],
        capture_output=True, text=True, timeout=30
    )
    result = subprocess.run(
        ["make", "-C", "/app"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert os.path.exists("/app/libfp8.so"), "libfp8.so not found after build"


@pytest.fixture(scope="session")
def fp8(build_library):
    """Load the fp8_ctypes module."""
    sys.path.insert(0, '/app')
    import fp8_ctypes
    return fp8_ctypes


# ============================================================
# Helper
# ============================================================

def is_fp8_nan(raw):
    return ((raw >> 3) & 0xF) == 15 and (raw & 0x7) != 0


# ============================================================
# Decode: FP8 raw -> float (via C library)
# ============================================================

class TestDecode:
    def test_positive_zero(self, fp8):
        v = fp8.fp8_to_float(0x00)
        assert v == 0.0
        assert math.copysign(1.0, v) == 1.0

    def test_negative_zero(self, fp8):
        v = fp8.fp8_to_float(0x80)
        assert v == 0.0
        assert math.copysign(1.0, v) == -1.0

    def test_one(self, fp8):
        assert fp8.fp8_to_float(0x38) == 1.0

    def test_neg_one(self, fp8):
        assert fp8.fp8_to_float(0xB8) == -1.0

    def test_two(self, fp8):
        assert fp8.fp8_to_float(0x40) == 2.0

    def test_half(self, fp8):
        assert fp8.fp8_to_float(0x30) == 0.5

    def test_one_point_five(self, fp8):
        assert fp8.fp8_to_float(0x3C) == 1.5

    def test_max_normal(self, fp8):
        assert fp8.fp8_to_float(0x77) == 240.0

    def test_smallest_normal(self, fp8):
        assert fp8.fp8_to_float(0x08) == 0.015625

    def test_smallest_subnormal(self, fp8):
        assert fp8.fp8_to_float(0x01) == 1.0 / 512.0

    def test_largest_subnormal(self, fp8):
        assert fp8.fp8_to_float(0x07) == 7.0 / 512.0

    def test_positive_inf(self, fp8):
        assert fp8.fp8_to_float(0x78) == float('inf')

    def test_negative_inf(self, fp8):
        assert fp8.fp8_to_float(0xF8) == float('-inf')

    def test_nan(self, fp8):
        assert math.isnan(fp8.fp8_to_float(0x79))


# ============================================================
# Encode: float -> FP8 (via C library)
# ============================================================

class TestEncode:
    def test_one(self, fp8):
        assert fp8.fp8_from_float(1.0, 0) == 0x38

    def test_neg_one(self, fp8):
        assert fp8.fp8_from_float(-1.0, 0) == 0xB8

    def test_two(self, fp8):
        assert fp8.fp8_from_float(2.0, 0) == 0x40

    def test_zero(self, fp8):
        assert fp8.fp8_from_float(0.0, 0) == 0x00

    def test_neg_zero(self, fp8):
        assert fp8.fp8_from_float(-0.0, 0) == 0x80

    def test_inf(self, fp8):
        assert fp8.fp8_from_float(float('inf'), 0) == 0x78

    def test_neg_inf(self, fp8):
        assert fp8.fp8_from_float(float('-inf'), 0) == 0xF8

    def test_nan(self, fp8):
        assert is_fp8_nan(fp8.fp8_from_float(float('nan'), 0))

    def test_max_normal(self, fp8):
        assert fp8.fp8_from_float(240.0, 0) == 0x77

    def test_rounding_RNE(self, fp8):
        assert fp8.fp8_from_float(1.3, 0) == 0x3A  # closer to 1.25

    def test_rounding_RU(self, fp8):
        assert fp8.fp8_from_float(1.3, 2) == 0x3B  # toward +Inf -> 1.375

    def test_rounding_RD(self, fp8):
        assert fp8.fp8_from_float(1.3, 3) == 0x3A

    def test_rounding_RZ(self, fp8):
        assert fp8.fp8_from_float(1.3, 4) == 0x3A

    def test_overflow_RNE(self, fp8):
        assert fp8.fp8_from_float(300.0, 0) == 0x78

    def test_overflow_RZ(self, fp8):
        assert fp8.fp8_from_float(300.0, 4) == 0x77

    def test_neg_overflow_RD(self, fp8):
        assert fp8.fp8_from_float(-300.0, 3) == 0xF8

    def test_neg_overflow_RU(self, fp8):
        assert fp8.fp8_from_float(-300.0, 2) == 0xF7


# ============================================================
# Addition: basic
# ============================================================

class TestAddBasic:
    def test_one_plus_one(self, fp8):
        assert fp8.fp8_add(0x38, 0x38, 0) == 0x40

    def test_one_plus_half(self, fp8):
        assert fp8.fp8_add(0x38, 0x30, 0) == 0x3C

    def test_two_minus_one(self, fp8):
        assert fp8.fp8_add(0x40, 0xB8, 0) == 0x38

    def test_neg_one_plus_neg_one(self, fp8):
        assert fp8.fp8_add(0xB8, 0xB8, 0) == 0xC0

    def test_subnormal_plus_subnormal(self, fp8):
        assert fp8.fp8_add(0x01, 0x01, 0) == 0x02

    def test_subnormal_to_normal_boundary(self, fp8):
        assert fp8.fp8_add(0x07, 0x01, 0) == 0x08


# ============================================================
# Addition: special values
# ============================================================

class TestAddSpecial:
    def test_nan_plus_one(self, fp8):
        assert is_fp8_nan(fp8.fp8_add(0x79, 0x38, 0))

    def test_one_plus_nan(self, fp8):
        assert is_fp8_nan(fp8.fp8_add(0x38, 0x79, 0))

    def test_inf_plus_one(self, fp8):
        assert fp8.fp8_add(0x78, 0x38, 0) == 0x78

    def test_inf_plus_neg_inf_is_nan(self, fp8):
        assert is_fp8_nan(fp8.fp8_add(0x78, 0xF8, 0))

    def test_inf_plus_inf(self, fp8):
        assert fp8.fp8_add(0x78, 0x78, 0) == 0x78

    def test_pos_zero_plus_neg_zero_RNE(self, fp8):
        assert fp8.fp8_add(0x00, 0x80, 0) == 0x00

    def test_pos_zero_plus_neg_zero_RD(self, fp8):
        assert fp8.fp8_add(0x00, 0x80, 3) == 0x80

    def test_x_minus_x_positive_zero(self, fp8):
        assert fp8.fp8_add(0x3C, 0xBC, 0) == 0x00

    def test_x_minus_x_negative_zero_RD(self, fp8):
        assert fp8.fp8_add(0x3C, 0xBC, 3) == 0x80


# ============================================================
# Addition: rounding and overflow
# ============================================================

class TestAddRounding:
    def test_overflow_RNE(self, fp8):
        assert fp8.fp8_add(0x77, 0x58, 0) == 0x78

    def test_overflow_RZ(self, fp8):
        assert fp8.fp8_add(0x77, 0x58, 4) == 0x77

    def test_overflow_RD(self, fp8):
        assert fp8.fp8_add(0x77, 0x58, 3) == 0x77

    def test_overflow_RU(self, fp8):
        assert fp8.fp8_add(0x77, 0x58, 2) == 0x78

    def test_tie_to_even_round_down(self, fp8):
        assert fp8.fp8_add(0x38, 0x18, 0) == 0x38

    def test_tie_to_even_round_up(self, fp8):
        assert fp8.fp8_add(0x39, 0x18, 0) == 0x3A

    def test_tie_away_from_zero(self, fp8):
        assert fp8.fp8_add(0x38, 0x18, 1) == 0x39


# ============================================================
# Multiplication: basic
# ============================================================

class TestMulBasic:
    def test_one_times_one(self, fp8):
        assert fp8.fp8_mul(0x38, 0x38, 0) == 0x38

    def test_two_times_three(self, fp8):
        assert fp8.fp8_mul(0x40, 0x44, 0) == 0x4C

    def test_one_point_five_squared(self, fp8):
        assert fp8.fp8_mul(0x3C, 0x3C, 0) == 0x41

    def test_neg_times_pos(self, fp8):
        assert fp8.fp8_mul(0xB8, 0x40, 0) == 0xC0

    def test_neg_times_neg(self, fp8):
        assert fp8.fp8_mul(0xB8, 0xB8, 0) == 0x38


# ============================================================
# Multiplication: special values
# ============================================================

class TestMulSpecial:
    def test_zero_times_inf_is_nan(self, fp8):
        assert is_fp8_nan(fp8.fp8_mul(0x00, 0x78, 0))

    def test_inf_times_two(self, fp8):
        assert fp8.fp8_mul(0x78, 0x40, 0) == 0x78

    def test_neg_inf_times_pos(self, fp8):
        assert fp8.fp8_mul(0xF8, 0x40, 0) == 0xF8

    def test_nan_times_one(self, fp8):
        assert is_fp8_nan(fp8.fp8_mul(0x79, 0x38, 0))


# ============================================================
# Multiplication: rounding
# ============================================================

class TestMulRounding:
    def test_overflow_RNE(self, fp8):
        assert fp8.fp8_mul(0x58, 0x58, 0) == 0x78

    def test_overflow_RZ(self, fp8):
        assert fp8.fp8_mul(0x58, 0x58, 4) == 0x77

    def test_round_down_RNE(self, fp8):
        assert fp8.fp8_mul(0x39, 0x39, 0) == 0x3A

    def test_round_up_RU(self, fp8):
        assert fp8.fp8_mul(0x39, 0x39, 2) == 0x3B

    def test_underflow_to_subnormal(self, fp8):
        assert fp8.fp8_mul(0x08, 0x30, 0) == 0x04

    def test_subnormal_rounding_tie_even(self, fp8):
        assert fp8.fp8_mul(0x09, 0x30, 0) == 0x04

    def test_subnormal_rounding_tie_away(self, fp8):
        assert fp8.fp8_mul(0x09, 0x30, 1) == 0x05


# ============================================================
# Fused multiply-add
# ============================================================

class TestFMA:
    def test_basic(self, fp8):
        assert fp8.fp8_fma(0x40, 0x44, 0x38, 0) == 0x4E

    def test_fma_differs_case1(self, fp8):
        result = fp8.fp8_fma(0x39, 0x39, 0xBA, 0)
        assert result == 0x08
        sep = fp8.fp8_add(fp8.fp8_mul(0x39, 0x39, 0), 0xBA, 0)
        assert sep == 0x00

    def test_fma_differs_case2(self, fp8):
        result = fp8.fp8_fma(0x3F, 0x39, 0xC0, 0)
        assert result == 0x1E
        sep = fp8.fp8_add(fp8.fp8_mul(0x3F, 0x39, 0), 0xC0, 0)
        assert sep == 0x00

    def test_zero_times_inf_is_nan(self, fp8):
        assert is_fp8_nan(fp8.fp8_fma(0x00, 0x78, 0x38, 0))

    def test_inf_product_minus_inf_is_nan(self, fp8):
        assert is_fp8_nan(fp8.fp8_fma(0x78, 0x38, 0xF8, 0))

    def test_finite_plus_inf(self, fp8):
        assert fp8.fp8_fma(0x38, 0x38, 0x78, 0) == 0x78


# ============================================================
# Classify
# ============================================================

class TestClassify:
    def test_zero(self, fp8):
        assert fp8.fp8_classify(0x00) == 2
        assert fp8.fp8_classify(0x80) == 2

    def test_subnormal(self, fp8):
        assert fp8.fp8_classify(0x01) == 1
        assert fp8.fp8_classify(0x07) == 1

    def test_normal(self, fp8):
        assert fp8.fp8_classify(0x38) == 0
        assert fp8.fp8_classify(0x77) == 0
        assert fp8.fp8_classify(0x08) == 0

    def test_infinity(self, fp8):
        assert fp8.fp8_classify(0x78) == 3
        assert fp8.fp8_classify(0xF8) == 3

    def test_nan(self, fp8):
        assert fp8.fp8_classify(0x79) == 4
        assert fp8.fp8_classify(0x7F) == 4


# ============================================================
# Compare
# ============================================================

class TestCompare:
    def test_less_than(self, fp8):
        assert fp8.fp8_compare(0x38, 0x40) == -1

    def test_greater_than(self, fp8):
        assert fp8.fp8_compare(0x40, 0x38) == 1

    def test_equal(self, fp8):
        assert fp8.fp8_compare(0x38, 0x38) == 0

    def test_pos_zero_eq_neg_zero(self, fp8):
        assert fp8.fp8_compare(0x00, 0x80) == 0

    def test_nan_unordered(self, fp8):
        assert fp8.fp8_compare(0x79, 0x38) == 2

    def test_nan_unordered_with_nan(self, fp8):
        assert fp8.fp8_compare(0x79, 0x79) == 2

    def test_neg_inf_less_than_pos(self, fp8):
        assert fp8.fp8_compare(0xF8, 0x38) == -1

    def test_negative_ordering(self, fp8):
        assert fp8.fp8_compare(0xB8, 0xC0) == 1


# ============================================================
# Verilog adder simulation via iverilog
# ============================================================

class TestVerilogAdder:
    """Test the Verilog fp8_adder module via Icarus Verilog simulation."""

    @pytest.fixture(scope="class", autouse=True)
    def compile_and_run(self):
        """Compile and run the Verilog simulation."""
        # Compile
        comp = subprocess.run(
            ["iverilog", "-o", "/tmp/fp8_sim",
             "/app/fp8_adder.v", "/tests/fp8_adder_tb.v"],
            capture_output=True, text=True, timeout=30
        )
        assert comp.returncode == 0, \
            f"iverilog compilation failed:\n{comp.stderr}"

        # Simulate
        sim = subprocess.run(
            ["vvp", "/tmp/fp8_sim"],
            capture_output=True, text=True, timeout=30
        )
        assert sim.returncode == 0, \
            f"vvp simulation failed:\n{sim.stderr}"

        # Parse results: lines of "R <a> <b> <rounding> <result>"
        results = {}
        for line in sim.stdout.strip().split('\n'):
            if line.startswith('R '):
                parts = line.split()
                if len(parts) == 5:
                    a, b, r, res = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
                    results[(a, b, r)] = res
        self.__class__._results = results

    def _get(self, a, b, r):
        return self.__class__._results.get((a, b, r))

    # --- Basic addition ---
    def test_one_plus_one(self):
        assert self._get(0x38, 0x38, 0) == 0x40

    def test_one_plus_half(self):
        assert self._get(0x38, 0x30, 0) == 0x3C

    def test_two_minus_one(self):
        assert self._get(0x40, 0xB8, 0) == 0x38

    def test_neg_one_plus_neg_one(self):
        assert self._get(0xB8, 0xB8, 0) == 0xC0

    # --- Subnormal ---
    def test_subnormal_add(self):
        assert self._get(0x01, 0x01, 0) == 0x02

    def test_subnormal_to_normal(self):
        assert self._get(0x07, 0x01, 0) == 0x08

    # --- Special values ---
    def test_nan_propagation(self):
        r = self._get(0x79, 0x38, 0)
        assert r is not None and is_fp8_nan(r)

    def test_inf_plus_one(self):
        assert self._get(0x78, 0x38, 0) == 0x78

    def test_inf_plus_neg_inf(self):
        r = self._get(0x78, 0xF8, 0)
        assert r is not None and is_fp8_nan(r)

    def test_inf_plus_inf(self):
        assert self._get(0x78, 0x78, 0) == 0x78

    # --- Signed zeros ---
    def test_zero_plus_neg_zero_RNE(self):
        assert self._get(0x00, 0x80, 0) == 0x00

    def test_zero_plus_neg_zero_RD(self):
        assert self._get(0x00, 0x80, 3) == 0x80

    def test_cancel_to_pos_zero(self):
        assert self._get(0x3C, 0xBC, 0) == 0x00

    def test_cancel_to_neg_zero_RD(self):
        assert self._get(0x3C, 0xBC, 3) == 0x80

    # --- Overflow with rounding modes ---
    def test_overflow_RNE(self):
        assert self._get(0x77, 0x58, 0) == 0x78

    def test_overflow_RZ(self):
        assert self._get(0x77, 0x58, 4) == 0x77

    def test_overflow_RD(self):
        assert self._get(0x77, 0x58, 3) == 0x77

    def test_overflow_RU(self):
        assert self._get(0x77, 0x58, 2) == 0x78

    # --- Tie-breaking ---
    def test_tie_even_down(self):
        assert self._get(0x38, 0x18, 0) == 0x38

    def test_tie_even_up(self):
        assert self._get(0x39, 0x18, 0) == 0x3A

    def test_tie_away(self):
        assert self._get(0x38, 0x18, 1) == 0x39
