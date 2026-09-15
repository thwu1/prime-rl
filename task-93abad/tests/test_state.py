
"""Tests for correctly-rounded exp2m1f (2^x - 1 for float32).

Verifies the implementation at /app/exp2m1f.c against mpmath reference
computed at 200-bit precision. Uses a custom float32 rounding routine
to avoid double-rounding errors.
"""

import ctypes
import math
import os
import random
import struct
import subprocess
import sys

import mpmath
import pytest

mpmath.mp.prec = 200

# ---------------------------------------------------------------------------
# Utility: bit-level float32 manipulation
# ---------------------------------------------------------------------------

def float32_to_bits(f):
    """Convert a Python float to its IEEE 754 binary32 bit representation."""
    return struct.unpack('!I', struct.pack('!f', f))[0]


def bits_to_float32(u):
    """Convert IEEE 754 binary32 bits to a Python float."""
    return struct.unpack('!f', struct.pack('!I', u & 0xFFFFFFFF))[0]


def mpf_to_float32(val):
    """Convert an mpmath value to correctly-rounded IEEE 754 float32.

    Avoids the double-rounding problem by comparing against both
    neighbouring float32 candidates and picking the nearest (ties to even).
    """
    if mpmath.isnan(val):
        return float('nan')
    if not mpmath.isfinite(val):
        return float('inf') if val > 0 else float('-inf')
    if val == 0:
        return 0.0

    negative = val < 0
    abs_val = abs(val)

    # Approximate via double then float
    d = float(abs_val)
    if math.isinf(d):
        return -float('inf') if negative else float('inf')

    # d is finite as double but may exceed float32 max
    FLT_MAX_F32 = struct.unpack('!f', struct.pack('!I', 0x7F7FFFFF))[0]
    if d > FLT_MAX_F32:
        # Overflow threshold: FLT_MAX + ULP/2 = 2^128 - 2^103
        threshold = mpmath.ldexp(1, 128) - mpmath.ldexp(1, 103)
        if abs_val >= threshold:
            return -float('inf') if negative else float('inf')
        return -FLT_MAX_F32 if negative else FLT_MAX_F32

    fb = struct.pack('!f', d)
    center_bits = struct.unpack('!I', fb)[0]

    best_bits = center_bits
    best_dist = abs(abs_val - mpmath.mpf(struct.unpack('!f', struct.pack('!I', center_bits))[0]))

    for delta in (-1, 1):
        cb = center_bits + delta
        if cb < 0 or cb > 0x7F7FFFFF:
            continue
        cf = struct.unpack('!f', struct.pack('!I', cb))[0]
        dist = abs(abs_val - mpmath.mpf(cf))
        # Strictly closer, or tie broken by even mantissa bit
        if dist < best_dist or (dist == best_dist and cb % 2 == 0):
            best_dist = dist
            best_bits = cb

    result = struct.unpack('!f', struct.pack('!I', best_bits))[0]
    return -result if negative else result


# ---------------------------------------------------------------------------
# Reference implementation using mpmath
# ---------------------------------------------------------------------------

def ref_exp2m1f(x_float):
    """Correctly-rounded 2^x - 1 for float32 input, returned as float32."""
    if math.isnan(x_float):
        return float('nan')
    if x_float == float('inf'):
        return float('inf')
    if x_float == float('-inf'):
        return -1.0
    # Preserve sign of zero
    if x_float == 0.0:
        return x_float

    x_mp = mpmath.mpf(x_float)
    result = mpmath.power(2, x_mp) - 1
    return mpf_to_float32(result)


# ---------------------------------------------------------------------------
# Build and load the implementation
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def lib():
    """Compile /app/exp2m1f.c and load the shared library."""
    assert os.path.isfile("/app/exp2m1f.c"), (
        "/app/exp2m1f.c does not exist. "
        "The implementation must be provided at /app/exp2m1f.c."
    )

    result = subprocess.run(
        ["make", "-C", "/app", "clean"],
        capture_output=True, text=True,
    )

    result = subprocess.run(
        ["make", "-C", "/app", "all"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"Compilation failed (make returned {result.returncode}).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert os.path.isfile("/app/libexp2m1f.so"), "libexp2m1f.so not produced"

    so = ctypes.CDLL("/app/libexp2m1f.so")
    so.cr_exp2m1f.argtypes = [ctypes.c_float]
    so.cr_exp2m1f.restype = ctypes.c_float
    return so


def call(lib, x):
    """Call cr_exp2m1f and return a Python float."""
    return lib.cr_exp2m1f(ctypes.c_float(x))


def assert_equal_float32(lib, x, expected=None):
    """Assert that cr_exp2m1f(x) == expected (bit-exact)."""
    if expected is None:
        expected = ref_exp2m1f(x)
    actual = call(lib, x)

    if math.isnan(expected):
        assert math.isnan(actual), (
            f"cr_exp2m1f({x!r}) = {actual!r}, expected NaN"
        )
        return

    a_bits = float32_to_bits(actual)
    e_bits = float32_to_bits(expected)
    assert a_bits == e_bits, (
        f"cr_exp2m1f({x:.8e} [0x{float32_to_bits(x):08x}]) = "
        f"{actual:.8e} [0x{a_bits:08x}], "
        f"expected {expected:.8e} [0x{e_bits:08x}]"
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestSpecialValues:
    """IEEE 754 special-value handling."""

    def test_positive_zero(self, lib):
        actual = call(lib, 0.0)
        bits = float32_to_bits(actual)
        assert bits == 0x00000000, f"cr_exp2m1f(+0) should be +0, got 0x{bits:08x}"

    def test_negative_zero(self, lib):
        neg_zero = bits_to_float32(0x80000000)
        actual = call(lib, neg_zero)
        bits = float32_to_bits(actual)
        assert bits == 0x80000000, f"cr_exp2m1f(-0) should be -0, got 0x{bits:08x}"

    def test_positive_inf(self, lib):
        actual = call(lib, float('inf'))
        assert actual == float('inf'), f"cr_exp2m1f(+Inf) should be +Inf, got {actual}"

    def test_negative_inf(self, lib):
        actual = call(lib, float('-inf'))
        assert actual == -1.0, f"cr_exp2m1f(-Inf) should be -1, got {actual}"

    def test_nan(self, lib):
        actual = call(lib, float('nan'))
        assert math.isnan(actual), f"cr_exp2m1f(NaN) should be NaN, got {actual}"


class TestExactResults:
    """Inputs where the exact mathematical result is a float."""

    @pytest.mark.parametrize("x,expected", [
        (1.0, 1.0),       # 2^1 - 1 = 1
        (2.0, 3.0),       # 2^2 - 1 = 3
        (3.0, 7.0),       # 2^3 - 1 = 7
        (4.0, 15.0),      # 2^4 - 1 = 15
        (5.0, 31.0),      # 2^5 - 1 = 31
        (8.0, 255.0),     # 2^8 - 1 = 255
        (10.0, 1023.0),   # 2^10 - 1 = 1023
        (23.0, 8388607.0),  # 2^23 - 1
        (-1.0, -0.5),     # 2^-1 - 1 = -0.5
        (-2.0, -0.75),    # 2^-2 - 1 = -0.75
    ])
    def test_exact(self, lib, x, expected):
        assert_equal_float32(lib, x, expected)


class TestOverflow:
    """Overflow boundary (2^128 > FLT_MAX ~ 3.4e38)."""

    def test_overflow_128(self, lib):
        actual = call(lib, 128.0)
        assert math.isinf(actual) and actual > 0, (
            f"cr_exp2m1f(128) should be +Inf, got {actual}"
        )

    @pytest.mark.parametrize("x", [200.0, 1000.0, 1e30])
    def test_large_overflow(self, lib, x):
        # Clamp to float range first
        x = bits_to_float32(float32_to_bits(x))
        actual = call(lib, x)
        assert math.isinf(actual) and actual > 0

    def test_just_below_overflow(self, lib):
        # 2^127.99... is below FLT_MAX threshold but the result for x just
        # below 128 is huge but finite.
        x = bits_to_float32(float32_to_bits(127.0))
        assert_equal_float32(lib, x)

    @pytest.mark.parametrize("bits", [
        0x42FE0000,  # 127.0
        0x42FF0000,  # 127.5
        0x42FFFC00,  # ~127.96875
        0x42FFFE00,  # ~127.984375
        0x42FFFF00,  # ~127.9921875
        0x42FFFF80,  # ~127.99609375
        0x42FFFFC0,  # ~127.998046875
        0x42FFFFE0,  # ~127.9990234375
        0x42FFFFF0,  # ~127.99951...
        0x42FFFFF8,  # ~127.99975...
        0x42FFFFFC,  # ~127.99987...
        0x42FFFFFE,  # ~127.99993...
        0x42FFFFFF,  # ~127.99999... (largest float < 128)
    ])
    def test_near_overflow_boundary(self, lib, bits):
        x = bits_to_float32(bits)
        assert_equal_float32(lib, x)


class TestNearZero:
    """Near x = 0 where 2^x - 1 ~ x*ln(2), testing cancellation handling."""

    @pytest.mark.parametrize("bits", [
        0x00000001,  # smallest positive subnormal
        0x00000002,
        0x00000010,
        0x00000100,
        0x00001000,
        0x00010000,
        0x00400000,  # large subnormal
        0x007FFFFF,  # largest subnormal
        0x00800000,  # smallest positive normal
        0x00800001,
        0x20000000,  # 2^-63
        0x25800000,  # 2^-52
        0x2F800000,  # 2^-32
        0x33000000,  # 2^-25 ~ 2.98e-8
        0x33800000,  # 2^-24
        0x34000000,  # 2^-23
        0x38000000,  # 2^-15
        0x3A000000,  # 2^-11
        0x3C000000,  # 2^-7
        0x3D800000,  # 2^-4 = 0.0625
        0x3E000000,  # 2^-3 = 0.125
        0x3E800000,  # 0.25
    ])
    def test_small_positive(self, lib, bits):
        x = bits_to_float32(bits)
        assert_equal_float32(lib, x)

    @pytest.mark.parametrize("bits", [
        0x80000001,  # smallest negative subnormal
        0x80000010,
        0x80800000,  # smallest negative normal
        0xB3000000,  # -2^-25
        0xB3800000,  # -2^-24
        0xB4000000,  # -2^-23
        0xBD800000,  # -2^-4
        0xBE000000,  # -0.125
        0xBE800000,  # -0.25
    ])
    def test_small_negative(self, lib, bits):
        x = bits_to_float32(bits)
        assert_equal_float32(lib, x)


class TestNearMinusOne:
    """Large negative x where result is near -1."""

    @pytest.mark.parametrize("x", [
        -24.0, -24.5, -25.0, -25.5, -26.0,
        -30.0, -50.0, -100.0, -126.0, -127.0,
        -149.0, -150.0,
    ])
    def test_near_minus_one(self, lib, x):
        assert_equal_float32(lib, x)

    @pytest.mark.parametrize("bits", [
        0xC1C00000,  # -24
        0xC1C80000,  # -25
        0xC1C40000,  # -24.5
        0xC1BFFFFF,  # just above -24
        0xC1C00001,  # just below -24
        0xC1C7FFFF,  # just above -25
        0xC1C80001,  # just below -25
    ])
    def test_minus_one_boundary_bits(self, lib, bits):
        x = bits_to_float32(bits)
        assert_equal_float32(lib, x)


class TestTableBoundaries:
    """Inputs x = j/32 that align exactly with table entries."""

    @pytest.mark.parametrize("j", range(32))
    def test_positive_table_entry(self, lib, j):
        x = j / 32.0
        x = bits_to_float32(float32_to_bits(x))  # ensure float32
        assert_equal_float32(lib, x)

    @pytest.mark.parametrize("j", range(1, 32))
    def test_negative_table_entry(self, lib, j):
        x = -j / 32.0
        x = bits_to_float32(float32_to_bits(x))
        assert_equal_float32(lib, x)


class TestMiscValues:
    """Various manually chosen values covering different code paths."""

    @pytest.mark.parametrize("x", [
        0.5, -0.5, 0.1, -0.1, 0.01, -0.01,
        1.5, 2.5, 3.5, 10.5,
        -3.0, -4.0, -5.0, -10.0, -15.0, -20.0,
        0.693147, -0.693147,  # near ln(2)
        1.4426950,            # near 1/ln(2)
        0.30103,              # log10(2)
        100.0, 120.0, 125.0,
    ])
    def test_misc(self, lib, x):
        x = bits_to_float32(float32_to_bits(x))
        assert_equal_float32(lib, x)


class TestRandomSample:
    """Pseudo-random sample across the full float range."""

    def _gen_inputs(self):
        rng = random.Random(42)
        inputs = []

        # Positive normals, moderate range
        for _ in range(300):
            x = rng.uniform(-25.0, 127.9)
            inputs.append(bits_to_float32(float32_to_bits(x)))

        # Near-zero region
        for _ in range(200):
            exp = rng.randint(-40, -1)
            mant = rng.random()
            x = (1.0 + mant) * (2.0 ** exp)
            if rng.random() < 0.5:
                x = -x
            inputs.append(bits_to_float32(float32_to_bits(x)))

        # Positive normals full range (random bit patterns)
        for _ in range(300):
            # exponent in [1, 254] (normal range), biased
            exp_bits = rng.randint(1, 254)
            mant_bits = rng.randint(0, (1 << 23) - 1)
            sign = rng.choice([0, 1])
            bits = (sign << 31) | (exp_bits << 23) | mant_bits
            x = bits_to_float32(bits)
            if math.isfinite(x):
                inputs.append(x)

        # Subnormals
        for _ in range(50):
            bits = rng.randint(1, 0x007FFFFF)
            if rng.random() < 0.5:
                bits |= 0x80000000
            inputs.append(bits_to_float32(bits))

        # Near overflow boundary
        for _ in range(50):
            x = rng.uniform(120.0, 128.0)
            inputs.append(bits_to_float32(float32_to_bits(x)))

        # Near -1 boundary
        for _ in range(50):
            x = rng.uniform(-150.0, -20.0)
            inputs.append(bits_to_float32(float32_to_bits(x)))

        return inputs

    def test_random_sample(self, lib):
        inputs = self._gen_inputs()
        failures = []
        for x in inputs:
            if not math.isfinite(x):
                continue
            expected = ref_exp2m1f(x)
            actual = call(lib, x)

            if math.isnan(expected):
                if not math.isnan(actual):
                    failures.append((x, actual, expected))
                continue

            a_bits = float32_to_bits(actual)
            e_bits = float32_to_bits(expected)
            if a_bits != e_bits:
                failures.append((x, actual, expected))

        if failures:
            msg_lines = [f"Failed {len(failures)}/{len(inputs)} inputs:"]
            for x, actual, expected in failures[:20]:
                msg_lines.append(
                    f"  cr_exp2m1f({x:.8e} [0x{float32_to_bits(x):08x}]) = "
                    f"{actual:.8e} [0x{float32_to_bits(actual):08x}], "
                    f"expected {expected:.8e} [0x{float32_to_bits(expected):08x}]"
                )
            if len(failures) > 20:
                msg_lines.append(f"  ... and {len(failures) - 20} more")
            pytest.fail("\n".join(msg_lines))


class TestHardCases:
    """Specific hard-to-round cases where 2^x - 1 is near a float32 midpoint."""

    @pytest.mark.parametrize("bits", [
        # Inputs near where result bit 25 flips
        0x3DAAAAAB,  # ~0.0833333
        0x3F317218,  # ~0.693147 (ln 2)
        0x3FB8AA3B,  # ~1.44269 (1/ln 2)
        0x411FFFFF,  # ~9.999...
        0x41200000,  # 10.0
        0x41200001,  # 10.000001
        0xC0000000,  # -2.0
        0xC0800000,  # -4.0
        0xBF800000,  # -1.0
        0x3F000000,  # 0.5
        0xBF000000,  # -0.5
        0x3E9E0652,  # ~0.3085 (log10(2)/log10(e) related)
        0x41A00000,  # 20.0
        0x41F00000,  # 30.0
        0x42700000,  # 60.0
        0x42C80000,  # 100.0
        0x42F00000,  # 120.0
        0x42FA0000,  # 125.0
        0xC2C80000,  # -100.0
        0xC2160000,  # -37.5
        0xC1B80000,  # -23.0
        0x3C23D70A,  # ~0.01
        0x3A83126F,  # ~0.001
        0x38D1B717,  # ~0.0001
        0x3727C5AC,  # ~0.00001
    ])
    def test_hard_case(self, lib, bits):
        x = bits_to_float32(bits)
        assert_equal_float32(lib, x)
