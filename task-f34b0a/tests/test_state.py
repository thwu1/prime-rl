"""
test_state.py — Pytest tests for posit16 arithmetic library.

Verifies both build system correctness (shared library, symbol exports, runtime
resolution) and arithmetic correctness (p16_mul, p16_div, q16_fdp_add, q16_to_p16)
against a Python reference implementation using exact Fraction arithmetic.

"""

import subprocess
import os
import glob
import random
import bisect
import pytest
from fractions import Fraction


BINARY_PATH = "/app/build/test_driver"
LIBRARY_GLOB = "/app/build/libposit16.so*"


# ===========================================================================
# Reference posit16 implementation using exact rational arithmetic
# ===========================================================================

def p16_decode(ui):
    """Decode posit16 bit pattern to exact Fraction. Returns None for NaR."""
    ui = ui & 0xFFFF
    if ui == 0:
        return Fraction(0)
    if ui == 0x8000:
        return None

    sign = (ui >> 15) & 1
    if sign:
        ui = (-ui) & 0xFFFF

    reg_s = (ui >> 14) & 1
    tmp = (ui << 2) & 0xFFFF
    k = 0

    if reg_s:
        while (tmp >> 15) & 1:
            k += 1
            tmp = (tmp << 1) & 0xFFFF
    else:
        k = -1
        while not ((tmp >> 15) & 1):
            k -= 1
            tmp = (tmp << 1) & 0xFFFF
        tmp &= 0x7FFF

    exp_bit = (tmp >> 14) & 1
    frac_with_hidden = (tmp & 0x3FFF) | 0x4000

    total_exp = 2 * k + exp_bit - 14

    if total_exp >= 0:
        value = Fraction(frac_with_hidden * (1 << total_exp))
    else:
        value = Fraction(frac_with_hidden, 1 << (-total_exp))

    if sign:
        value = -value

    return value


# Precomputed sorted posit16 table for rounding
_sorted_vals = None
_sorted_uis = None


def _init_table():
    global _sorted_vals, _sorted_uis
    entries = []
    for ui in range(65536):
        if ui == 0x8000:
            continue
        val = p16_decode(ui)
        if val is not None:
            entries.append((val, ui))
    entries.sort()
    _sorted_vals = [e[0] for e in entries]
    _sorted_uis = [e[1] for e in entries]


def round_to_p16(exact_val):
    """Round an exact Fraction to the nearest posit16 with round-to-nearest-even."""
    if _sorted_vals is None:
        _init_table()

    idx = bisect.bisect_left(_sorted_vals, exact_val)

    # Exact match
    if idx < len(_sorted_vals) and _sorted_vals[idx] == exact_val:
        return _sorted_uis[idx]

    # Boundary: clamp
    if idx == 0:
        return _sorted_uis[0]
    if idx >= len(_sorted_vals):
        return _sorted_uis[-1]

    lo_val, lo_ui = _sorted_vals[idx - 1], _sorted_uis[idx - 1]
    hi_val, hi_ui = _sorted_vals[idx], _sorted_uis[idx]

    dist_lo = exact_val - lo_val
    dist_hi = hi_val - exact_val

    if dist_lo < dist_hi:
        return lo_ui
    elif dist_hi < dist_lo:
        return hi_ui
    else:
        # Tie: round to even (even = last bit of ui is 0)
        return lo_ui if (lo_ui & 1) == 0 else hi_ui


def _is_regime_boundary(ui):
    """Check if a posit16 value is at the extreme regime boundary."""
    ui = ui & 0xFFFF
    if ui <= 0x0002:
        return True
    if 0x7FFD <= ui <= 0x7FFF:
        return True
    if 0xFFFE <= ui <= 0xFFFF or ui == 0x0000:
        return True
    if 0x8001 <= ui <= 0x8003:
        return True
    return False


def ref_mul(a_ui, b_ui):
    """Reference posit16 multiplication."""
    va = p16_decode(a_ui)
    vb = p16_decode(b_ui)
    if va is None or vb is None:
        return 0x8000
    if va == 0 or vb == 0:
        return 0x0000
    return round_to_p16(va * vb)


def ref_div(a_ui, b_ui):
    """Reference posit16 division."""
    va = p16_decode(a_ui)
    vb = p16_decode(b_ui)
    if va is None or vb is None:
        return 0x8000
    if vb == 0:
        return 0x8000
    if va == 0:
        return 0x0000
    return round_to_p16(va / vb)


def ref_fdp(pairs):
    """Reference fused dot product: exact sum of products, then round."""
    total = Fraction(0)
    for a_ui, b_ui in pairs:
        va = p16_decode(a_ui)
        vb = p16_decode(b_ui)
        if va is None or vb is None:
            return 0x8000
        total += va * vb
    return round_to_p16(total)


# ===========================================================================
# Test infrastructure
# ===========================================================================

def _find_library():
    """Find the posit16 shared library."""
    libs = sorted(glob.glob(LIBRARY_GLOB))
    return libs[0] if libs else None


def run_driver(mode, input_str):
    """Run the test_driver with given mode and stdin input.
    Sets LD_LIBRARY_PATH to /app/build/ so arithmetic tests can run
    even if RPATH is not yet configured."""
    if not os.path.isfile(BINARY_PATH):
        pytest.fail(f"{BINARY_PATH} not found — build the project first")

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = "/app/build:" + env.get("LD_LIBRARY_PATH", "")

    r = subprocess.run(
        [BINARY_PATH, mode],
        input=input_str,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 0, f"test_driver exited {r.returncode}:\n{r.stderr}"
    lines = r.stdout.strip().split("\n")
    return lines


@pytest.fixture(scope="session", autouse=True)
def setup():
    _init_table()


# ===========================================================================
# Build system tests
# ===========================================================================

class TestBuildSystem:
    """Verify CMake build produces correct artifacts."""

    def test_binary_exists(self):
        assert os.path.isfile(BINARY_PATH), (
            f"{BINARY_PATH} not found. "
            "Configure and build the CMake project under /app/build/."
        )

    def test_shared_library_exists(self):
        lib = _find_library()
        assert lib is not None, (
            "libposit16.so not found in /app/build/. "
            "The CMake project must produce a shared library."
        )

    def test_library_exports_symbols(self):
        lib = _find_library()
        if lib is None:
            pytest.skip("libposit16.so not found")

        result = subprocess.run(
            ["nm", "-D", "--defined-only", lib],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"nm failed on {lib}: {result.stderr}"

        required = [
            "p16_add", "p16_sub", "p16_mul", "p16_div",
            "q16_clr", "q16_fdp_add", "q16_to_p16", "p16_to_f64",
        ]
        missing = [s for s in required if s not in result.stdout]
        assert len(missing) == 0, (
            f"Shared library missing exported symbols: {missing}"
        )

    def test_runtime_library_resolution(self):
        if not os.path.isfile(BINARY_PATH):
            pytest.skip("test_driver not found")

        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        result = subprocess.run(
            ["ldd", BINARY_PATH],
            capture_output=True, text=True, env=env
        )
        assert "not found" not in result.stdout, (
            f"Shared library dependencies not resolved at runtime. "
            f"The binary must find libposit16.so via RPATH, not LD_LIBRARY_PATH.\n"
            f"{result.stdout}"
        )


# ===========================================================================
# Arithmetic tests
# ===========================================================================

class TestP16Mul:
    """Test posit16 multiplication for bit-exact correctness."""

    def _generate_pairs(self):
        rng = random.Random(42)
        pairs = []
        special = [0x0000, 0x0010, 0x0100, 0x2000, 0x3000, 0x4000,
                   0x4800, 0x5000, 0x6000, 0x7000, 0x7F00,
                   0x8000, 0x8100, 0x9000, 0xB000, 0xC000, 0xF000]
        for a in special:
            for b in special:
                pairs.append((a, b))
        for _ in range(20000):
            a = rng.randint(0, 0xFFFF)
            b = rng.randint(0, 0xFFFF)
            pairs.append((a, b))
        return pairs

    def test_mul_correctness(self):
        pairs = self._generate_pairs()
        input_str = "".join(f"MUL {a:04x} {b:04x}\n" for a, b in pairs)
        results = run_driver("binop", input_str)

        failures = []
        for i, (a, b) in enumerate(pairs):
            expected = ref_mul(a, b)
            actual = int(results[i], 16)
            if actual != expected:
                if _is_regime_boundary(actual) and _is_regime_boundary(expected):
                    continue
                failures.append((a, b, expected, actual))

        assert len(failures) == 0, (
            f"p16_mul: {len(failures)}/{len(pairs)} failures. "
            f"First 5: {failures[:5]}"
        )


class TestP16Div:
    """Test posit16 division for bit-exact correctness."""

    def _generate_pairs(self):
        rng = random.Random(137)
        pairs = []
        special = [0x0000, 0x0010, 0x0100, 0x2000, 0x3000, 0x4000,
                   0x4800, 0x5000, 0x6000, 0x7000, 0x7F00,
                   0x8000, 0x8100, 0x9000, 0xB000, 0xC000, 0xF000]
        for a in special:
            for b in special:
                pairs.append((a, b))
        for _ in range(20000):
            a = rng.randint(0, 0xFFFF)
            b = rng.randint(0, 0xFFFF)
            pairs.append((a, b))
        return pairs

    def test_div_correctness(self):
        pairs = self._generate_pairs()
        input_str = "".join(f"DIV {a:04x} {b:04x}\n" for a, b in pairs)
        results = run_driver("binop", input_str)

        failures = []
        for i, (a, b) in enumerate(pairs):
            expected = ref_div(a, b)
            actual = int(results[i], 16)
            if actual != expected:
                if _is_regime_boundary(actual) and _is_regime_boundary(expected):
                    continue
                failures.append((a, b, expected, actual))

        assert len(failures) == 0, (
            f"p16_div: {len(failures)}/{len(pairs)} failures. "
            f"First 5: {failures[:5]}"
        )


class TestQ16FDP:
    """Test quire16 fused dot-product for bit-exact correctness."""

    def _generate_vectors(self):
        rng = random.Random(271)
        vectors = []
        vectors.append([(0x4000, 0x4000)])
        vectors.append([(0x4000, 0x4000), (0x4000, 0x4000)])
        vectors.append([(0x5000, 0x5000)])
        vectors.append([(0x4800, 0x4800), (0x4800, 0x4800)])
        vectors.append([(0x7FFF, 0x4000), (0x8001, 0x4000)])

        vectors.append([
            (0x7000, 0x7000),
            (0x7000, 0x9000),
        ])

        for _ in range(100):
            length = rng.randint(2, 16)
            vec = []
            for _ in range(length):
                a = rng.randint(0, 0xFFFF)
                b = rng.randint(0, 0xFFFF)
                if a == 0x8000:
                    a = 0x4000
                if b == 0x8000:
                    b = 0x4000
                vec.append((a, b))
            vectors.append(vec)

        vectors.append([(0x8000, 0x4000)])
        vectors.append([(0x4000, 0x4000), (0x8000, 0x5000)])

        return vectors

    def test_fdp_correctness(self):
        vectors = self._generate_vectors()
        input_lines = []
        for vec in vectors:
            parts = [str(len(vec))]
            for a, b in vec:
                parts.append(f"{a:04x}")
                parts.append(f"{b:04x}")
            input_lines.append(" ".join(parts))

        input_str = "\n".join(input_lines) + "\n"
        results = run_driver("fdp", input_str)

        failures = []
        for i, vec in enumerate(vectors):
            expected = ref_fdp(vec)
            actual = int(results[i], 16)
            if actual != expected:
                if _is_regime_boundary(actual) and _is_regime_boundary(expected):
                    continue
                failures.append((i, vec[:3], expected, actual))

        assert len(failures) == 0, (
            f"q16_fdp: {len(failures)}/{len(vectors)} failures. "
            f"First 5: {failures[:5]}"
        )


class TestP16Add:
    """Smoke test: verify that p16_add still works (regression guard)."""

    def test_add_basic(self):
        pairs = [
            (0x4000, 0x4000),
            (0x5000, 0x4000),
            (0x0000, 0x4000),
            (0x4000, 0xC000),
            (0x8000, 0x4000),
        ]
        expected = [0x5000, 0x5800, 0x4000, 0x0000, 0x8000]

        input_str = "".join(f"ADD {a:04x} {b:04x}\n" for a, b in pairs)
        results = run_driver("binop", input_str)

        for i, (a, b) in enumerate(pairs):
            actual = int(results[i], 16)
            assert actual == expected[i], (
                f"p16_add(0x{a:04x}, 0x{b:04x}) = 0x{actual:04x}, "
                f"expected 0x{expected[i]:04x}"
            )
