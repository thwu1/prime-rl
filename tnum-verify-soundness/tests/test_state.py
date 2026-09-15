"""Tests for tnum abstract domain implementation."""

import pytest
import sys
import os
import json
import random

sys.path.insert(0, '/app')
from tnum import (
    Tnum, MASK, BITS,
    tnum_const, tnum_unknown,
    tnum_and, tnum_or, tnum_xor,
    tnum_add, tnum_sub,
    tnum_lshift, tnum_rshift,
    tnum_cast, tnum_intersect,
    tnum_mul, tnum_range,
)

SEED = 20240918
TRIALS = 3000


def rand_tnum(rng, max_bits=16):
    """Generate a random tnum with values fitting in max_bits."""
    bmask = (1 << max_bits) - 1
    m = rng.randint(0, bmask)
    v = rng.randint(0, bmask) & ~m
    return Tnum(v, m)


def rand_concrete(rng, t):
    """Pick a random concrete value from gamma(t)."""
    filler = rng.randint(0, MASK) & t.mask
    return t.value | filler


# ---------------------------------------------------------------------------
# Invariant tests: value & mask == 0 for all operations
# ---------------------------------------------------------------------------

class TestInvariant:
    def _check(self, result):
        if result is None:
            return
        assert result.value & result.mask == 0, f"Invariant violated: {result}"

    def test_and(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            self._check(tnum_and(rand_tnum(rng), rand_tnum(rng)))

    def test_or(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            self._check(tnum_or(rand_tnum(rng), rand_tnum(rng)))

    def test_xor(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            self._check(tnum_xor(rand_tnum(rng), rand_tnum(rng)))

    def test_add(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            self._check(tnum_add(rand_tnum(rng), rand_tnum(rng)))

    def test_sub(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            self._check(tnum_sub(rand_tnum(rng), rand_tnum(rng)))

    def test_mul(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            self._check(tnum_mul(rand_tnum(rng, 8), rand_tnum(rng, 8)))

    def test_lshift(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            self._check(tnum_lshift(rand_tnum(rng), rng.randint(0, 63)))

    def test_rshift(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            self._check(tnum_rshift(rand_tnum(rng), rng.randint(0, 63)))


# ---------------------------------------------------------------------------
# Soundness tests: concrete results must be in abstract results
# ---------------------------------------------------------------------------

class TestSoundness:
    def test_and(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            a, b = rand_tnum(rng), rand_tnum(rng)
            ca, cb = rand_concrete(rng, a), rand_concrete(rng, b)
            r = tnum_and(a, b)
            assert r.contains(ca & cb), f"{a} & {b}: {ca}&{cb}={ca&cb} not in {r}"

    def test_or(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            a, b = rand_tnum(rng), rand_tnum(rng)
            ca, cb = rand_concrete(rng, a), rand_concrete(rng, b)
            r = tnum_or(a, b)
            assert r.contains(ca | cb), f"{a} | {b}: {ca}|{cb}={ca|cb} not in {r}"

    def test_xor(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            a, b = rand_tnum(rng), rand_tnum(rng)
            ca, cb = rand_concrete(rng, a), rand_concrete(rng, b)
            r = tnum_xor(a, b)
            assert r.contains(ca ^ cb), f"{a} ^ {b}: {ca}^{cb}={ca^cb} not in {r}"

    def test_add(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            a, b = rand_tnum(rng), rand_tnum(rng)
            ca, cb = rand_concrete(rng, a), rand_concrete(rng, b)
            r = tnum_add(a, b)
            s = (ca + cb) & MASK
            assert r.contains(s), f"{a} + {b}: {ca}+{cb}={s} not in {r}"

    def test_sub(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            a, b = rand_tnum(rng), rand_tnum(rng)
            ca, cb = rand_concrete(rng, a), rand_concrete(rng, b)
            r = tnum_sub(a, b)
            s = (ca - cb) & MASK
            assert r.contains(s), f"{a} - {b}: {ca}-{cb}={s} not in {r}"

    def test_lshift(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            a = rand_tnum(rng)
            shift = rng.randint(0, 63)
            ca = rand_concrete(rng, a)
            r = tnum_lshift(a, shift)
            s = (ca << shift) & MASK
            assert r.contains(s), f"{a} << {shift}: {ca}<<{shift}={s} not in {r}"

    def test_rshift(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            a = rand_tnum(rng)
            shift = rng.randint(0, 63)
            ca = rand_concrete(rng, a)
            r = tnum_rshift(a, shift)
            s = (ca >> shift) & MASK
            assert r.contains(s), f"{a} >> {shift}: {ca}>>{shift}={s} not in {r}"

    def test_mul(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            a, b = rand_tnum(rng, 8), rand_tnum(rng, 8)
            ca = rand_concrete(rng, a) & 0xFF
            cb = rand_concrete(rng, b) & 0xFF
            r = tnum_mul(a, b)
            s = (ca * cb) & MASK
            assert r.contains(s), f"{a} * {b}: {ca}*{cb}={s} not in {r}"

    def test_intersect(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            a, b = rand_tnum(rng), rand_tnum(rng)
            ca = rand_concrete(rng, a)
            if b.contains(ca):
                r = tnum_intersect(a, b)
                assert r is not None, f"Compatible intersection returned None"
                assert r.contains(ca), f"intersect({a},{b}): {ca} not in {r}"

    def test_range(self):
        rng = random.Random(SEED)
        for _ in range(TRIALS):
            lo = rng.randint(0, 0xFFFF)
            span = rng.randint(0, 0xFF)
            hi = lo + span
            r = tnum_range(lo, hi)
            x = rng.randint(lo, hi)
            assert r.contains(x), f"range({lo},{hi}): {x} not in {r}"


# ---------------------------------------------------------------------------
# Regression tests for the three original bugs
# ---------------------------------------------------------------------------

class TestRegressions:
    def test_add_carry_propagation(self):
        """tnum_add must handle carries from unknown bits correctly.
        a={3}, b={0,1}. 3+1=4 must be in result."""
        a = Tnum(3, 0)
        b = Tnum(0, 1)
        r = tnum_add(a, b)
        assert r.contains(3), "3+0=3 must be in result"
        assert r.contains(4), "3+1=4 must be in result"

    def test_add_carry_propagation_2(self):
        """Another carry test: a={7}, b={0,1}. 7+1=8 must be in result."""
        a = Tnum(7, 0)
        b = Tnum(0, 1)
        r = tnum_add(a, b)
        assert r.contains(7), "7+0=7 must be in result"
        assert r.contains(8), "7+1=8 must be in result"

    def test_lshift_mask_shifted(self):
        """tnum_lshift must shift the mask, not just the value.
        a={0,1}, shift=2. 1<<2=4 must be in result."""
        a = Tnum(0, 1)
        r = tnum_lshift(a, 2)
        assert r.contains(0), "0<<2=0 must be in result"
        assert r.contains(4), "1<<2=4 must be in result"
        assert r == Tnum(0, 4), f"Expected Tnum(0x0, 0x4), got {r}"

    def test_lshift_mask_shifted_2(self):
        """a={2,3}, shift=1 -> {4,6}."""
        a = Tnum(2, 1)
        r = tnum_lshift(a, 1)
        assert r.contains(4), "2<<1=4 must be in result"
        assert r.contains(6), "3<<1=6 must be in result"
        assert r == Tnum(4, 2), f"Expected Tnum(0x4, 0x2), got {r}"

    def test_intersect_detects_conflict(self):
        """tnum_intersect must return None when known bits disagree."""
        a = Tnum(1, 0)
        b = Tnum(0, 0)
        r = tnum_intersect(a, b)
        assert r is None, f"Conflicting tnums must return None, got {r}"

    def test_intersect_detects_conflict_multibit(self):
        """Conflict detection with multiple known bits."""
        a = Tnum(0b1010, 0)
        b = Tnum(0b1001, 0)
        r = tnum_intersect(a, b)
        assert r is None, f"Conflicting tnums must return None, got {r}"

    def test_intersect_compatible(self):
        """Compatible tnums produce correct intersection."""
        a = Tnum(0, 0b11)
        b = Tnum(0b10, 0b01)
        r = tnum_intersect(a, b)
        assert r is not None
        assert r.contains(2)
        assert r.contains(3)
        assert not r.contains(0)
        assert not r.contains(1)


# ---------------------------------------------------------------------------
# tnum_mul precision tests
# ---------------------------------------------------------------------------

class TestMul:
    def test_const_mul(self):
        """Multiplication of known constants must be exact."""
        for x in [0, 1, 2, 3, 7, 13, 255]:
            for y in [0, 1, 2, 3, 5, 11, 127]:
                r = tnum_mul(tnum_const(x), tnum_const(y))
                expected = (x * y) & MASK
                assert r == tnum_const(expected), \
                    f"{x}*{y}: expected Tnum(0x{expected:x},0x0), got {r}"

    def test_mul_not_trivial(self):
        """tnum_mul must be more precise than returning tnum_unknown()."""
        a = Tnum(2, 0)
        b = Tnum(0, 1)
        r = tnum_mul(a, b)
        assert r.mask < MASK, f"tnum_mul too imprecise: {r}"
        assert r.contains(0)
        assert r.contains(2)

    def test_mul_with_unknowns(self):
        """tnum_mul with unknown bits."""
        a = Tnum(0, 0b11)  # {0,1,2,3}
        b = Tnum(1, 0)     # {1}
        r = tnum_mul(a, b)
        for v in range(4):
            assert r.contains(v), f"{v}*1={v} not in {r}"


# ---------------------------------------------------------------------------
# tnum_range precision tests
# ---------------------------------------------------------------------------

class TestRange:
    def test_singleton(self):
        for v in [0, 1, 42, 255, 1000]:
            r = tnum_range(v, v)
            assert r == tnum_const(v), f"range({v},{v}): expected const, got {r}"

    def test_power_of_two_aligned(self):
        r = tnum_range(0, 7)
        assert r == Tnum(0, 7), f"range(0,7): expected Tnum(0x0,0x7), got {r}"
        r = tnum_range(8, 15)
        assert r == Tnum(8, 7), f"range(8,15): expected Tnum(0x8,0x7), got {r}"

    def test_range_contains_endpoints(self):
        rng = random.Random(SEED)
        for _ in range(1000):
            lo = rng.randint(0, 0xFFFF)
            hi = rng.randint(lo, lo + rng.randint(0, 0xFFF))
            r = tnum_range(lo, hi)
            assert r.contains(lo), f"range({lo},{hi}) missing {lo}: {r}"
            assert r.contains(hi), f"range({lo},{hi}) missing {hi}: {r}"

    def test_range_exhaustive_small(self):
        """Range must contain all values for small ranges."""
        rng = random.Random(SEED)
        for _ in range(500):
            lo = rng.randint(0, 0xFF)
            hi = rng.randint(lo, lo + rng.randint(0, 0x1F))
            r = tnum_range(lo, hi)
            for v in range(lo, hi + 1):
                assert r.contains(v), f"range({lo},{hi}) missing {v}: {r}"

    def test_range_not_trivial(self):
        """tnum_range must be more precise than tnum_unknown()."""
        r = tnum_range(4, 7)
        assert r.mask < MASK, f"tnum_range too imprecise: {r}"
        assert r == Tnum(4, 3), f"range(4,7): expected Tnum(0x4,0x3), got {r}"


# ---------------------------------------------------------------------------
# Formal verification output tests
# ---------------------------------------------------------------------------

class TestVerification:
    def test_verify_script_exists(self):
        assert os.path.exists('/app/verify.py'), "verify.py must exist"

    def test_report_exists(self):
        assert os.path.exists('/app/verification_report.json'), \
            "verification_report.json must exist"

    def test_report_format(self):
        with open('/app/verification_report.json') as f:
            report = json.load(f)
        required = [
            'tnum_and', 'tnum_or', 'tnum_xor',
            'tnum_add', 'tnum_sub',
            'tnum_lshift', 'tnum_rshift',
            'tnum_intersect', 'tnum_mul', 'tnum_range',
        ]
        for op in required:
            assert op in report, f"Missing '{op}' in report"
            assert 'verified' in report[op], f"Missing 'verified' for '{op}'"
            assert 'bit_width' in report[op], f"Missing 'bit_width' for '{op}'"

    def test_all_verified(self):
        with open('/app/verification_report.json') as f:
            report = json.load(f)
        for op, data in report.items():
            assert data['verified'] is True, f"'{op}' not verified as sound"
