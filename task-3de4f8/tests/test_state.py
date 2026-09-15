"""Tests for the bitvector program synthesizer."""
import json
import os
import random
import sys

sys.path.insert(0, '/app')

from dsl import evaluate_program, validate_program, MASK, NUM_INPUTS
from oracle import get_oracle

# ---------------------------------------------------------------------------
# Shared verification infrastructure
# ---------------------------------------------------------------------------
NUM_VERIFY = 50000
_rng = random.Random(42)
VERIFY_INPUTS = [
    tuple(_rng.randint(0, MASK) for _ in range(NUM_INPUTS))
    for _ in range(NUM_VERIFY)
]


def _verify(program, oracle_fn):
    """Return (ok, failing_input, expected, actual)."""
    for inp in VERIFY_INPUTS:
        expected = oracle_fn(*inp)
        actual = evaluate_program(program, inp)
        if actual != expected:
            return False, inp, expected, actual
    return True, None, None, None


# ---------------------------------------------------------------------------
# Tests for the 5 provided oracles (results read from JSON)
# ---------------------------------------------------------------------------
class TestSynthesizedOracles:

    def _check(self, oid):
        path = f'/app/results/oracle_{oid}.json'
        assert os.path.exists(path), f"{path} not found"
        with open(path) as f:
            prog = json.load(f)
        assert validate_program(prog, max_lines=6), (
            f"Oracle {oid}: program fails structural validation"
        )
        oracle_fn = get_oracle(oid)
        ok, inp, exp, act = _verify(prog, oracle_fn)
        assert ok, (
            f"Oracle {oid}: wrong on {inp} (expected {exp}, got {act})"
        )

    def test_oracle_1(self):
        self._check(1)

    def test_oracle_2(self):
        self._check(2)

    def test_oracle_3(self):
        self._check(3)

    def test_oracle_4(self):
        self._check(4)

    def test_oracle_5(self):
        self._check(5)


# ---------------------------------------------------------------------------
# Generality tests: call synthesize() on *unseen* oracles
# ---------------------------------------------------------------------------
class TestSynthesizerGenerality:

    def _synth_and_check(self, oracle_fn, label):
        from synthesize import synthesize
        prog = synthesize(oracle_fn, max_lines=5)
        assert prog is not None, f"{label}: synthesize returned None"
        assert validate_program(prog, max_lines=6), (
            f"{label}: program fails structural validation"
        )
        ok, inp, exp, act = _verify(prog, oracle_fn)
        assert ok, (
            f"{label}: wrong on {inp} (expected {exp}, got {act})"
        )

    def test_hidden_oracle_a(self):
        """(a | b) ^ (c & d) -- 3 ops"""
        def fn(a, b, c, d):
            return ((a | b) ^ (c & d)) & MASK
        self._synth_and_check(fn, "hidden_a")

    def test_hidden_oracle_b(self):
        """(a + c) & (b ^ d) -- 3 ops"""
        def fn(a, b, c, d):
            return (((a + c) & MASK) & (b ^ d)) & MASK
        self._synth_and_check(fn, "hidden_b")

    def test_hidden_oracle_c(self):
        """((a ^ b) + c) * d -- 3 ops"""
        def fn(a, b, c, d):
            return ((((a ^ b) + c) & MASK) * d) & MASK
        self._synth_and_check(fn, "hidden_c")
