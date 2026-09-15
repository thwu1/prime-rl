"""
Exhaustive soundness and precision tests for KnownBits transfer functions,
plus cross-validation against LLVM's opt-18 instcombine pass.

Soundness: every concrete result must be contained in the abstract output.
Precision: fraction of knowable bits actually determined vs. the optimal.
Cross-validation: optimized IR and JSON report produced via opt-18.
Verification report: JSON with soundness/precision per operation.
"""

import sys
sys.path.insert(0, "/app")

import os
import json
import glob
import subprocess
import pytest
from knownbits import KnownBits
from transfer_functions import (
    transfer_add,
    transfer_sub,
    transfer_mul,
    transfer_shl,
    transfer_lshr,
    transfer_udiv,
)
from verifier import verify_soundness_binary, measure_precision_binary

W = 4  # verification bit-width


# ---- concrete operations (unsigned, mod 2^W) ----

def c_add(x, y):
    return x + y

def c_sub(x, y):
    return x - y

def c_mul(x, y):
    return x * y

def c_shl(x, y):
    return 0 if y >= 64 else (x << y)

def c_lshr(x, y):
    return 0 if y >= 64 else (x >> y)

def c_udiv(x, y):
    return 0 if y == 0 else x // y


# ================================================================
#  Soundness — all six must pass
# ================================================================

class TestSoundness:

    def _check(self, transfer_fn, concrete_op, name):
        ok, cex = verify_soundness_binary(transfer_fn, concrete_op, W)
        if not ok:
            a, b, x, y, conc, abst = cex
            pytest.fail(
                f"{name} unsound: a={a} b={b}  "
                f"concrete({x},{y})={conc}  abstract={abst}"
            )

    def test_add(self):
        self._check(transfer_add, c_add, "add")

    def test_sub(self):
        self._check(transfer_sub, c_sub, "sub")

    def test_mul(self):
        self._check(transfer_mul, c_mul, "mul")

    def test_shl(self):
        self._check(transfer_shl, c_shl, "shl")

    def test_lshr(self):
        self._check(transfer_lshr, c_lshr, "lshr")

    def test_udiv(self):
        self._check(transfer_udiv, c_udiv, "udiv")


# ================================================================
#  Precision thresholds
# ================================================================

class TestPrecision:

    def _check(self, transfer_fn, concrete_op, threshold, name):
        p = measure_precision_binary(transfer_fn, concrete_op, W)
        assert p >= threshold, (
            f"{name} precision {p:.4f} < {threshold}"
        )

    def test_add(self):
        self._check(transfer_add, c_add, 0.85, "add")

    def test_sub(self):
        self._check(transfer_sub, c_sub, 0.85, "sub")

    def test_mul(self):
        self._check(transfer_mul, c_mul, 0.55, "mul")

    def test_shl(self):
        self._check(transfer_shl, c_shl, 0.75, "shl")

    def test_lshr(self):
        self._check(transfer_lshr, c_lshr, 0.75, "lshr")

    def test_udiv(self):
        self._check(transfer_udiv, c_udiv, 0.35, "udiv")


# ================================================================
#  Spot checks — known edge cases
# ================================================================

class TestEdgeCases:

    def test_add_constants(self):
        """3 + 5 = 8 at 4-bit width."""
        a = KnownBits.from_constant(4, 3)
        b = KnownBits.from_constant(4, 5)
        r = transfer_add(a, b)
        assert r.contains(8) and r.num_known_bits() == 4

    def test_add_overflow(self):
        """15 + 1 = 0 at 4-bit width."""
        a = KnownBits.from_constant(4, 15)
        b = KnownBits.from_constant(4, 1)
        r = transfer_add(a, b)
        assert r.contains(0) and r.num_known_bits() == 4

    def test_sub_identity(self):
        """a - 0 == a."""
        a = KnownBits(4, 0b0001, 0b0100)  # KB("?1?0")
        b = KnownBits.from_constant(4, 0)
        r = transfer_sub(a, b)
        assert r == a

    def test_mul_by_zero(self):
        """Anything * 0 = 0."""
        a = KnownBits.top(4)
        b = KnownBits.from_constant(4, 0)
        r = transfer_mul(a, b)
        assert r == KnownBits.from_constant(4, 0)

    def test_shl_known_shift(self):
        """Constant << constant."""
        a = KnownBits.from_constant(4, 3)
        b = KnownBits.from_constant(4, 2)
        r = transfer_shl(a, b)
        assert r.contains(12) and r.num_known_bits() == 4

    def test_shl_overflow(self):
        """Any << 4 = 0 at 4-bit width."""
        a = KnownBits.top(4)
        b = KnownBits.from_constant(4, 4)
        r = transfer_shl(a, b)
        assert r == KnownBits.from_constant(4, 0)

    def test_lshr_known_shift(self):
        """12 >> 2 = 3."""
        a = KnownBits.from_constant(4, 12)
        b = KnownBits.from_constant(4, 2)
        r = transfer_lshr(a, b)
        assert r.contains(3) and r.num_known_bits() == 4

    def test_udiv_by_zero(self):
        """a / 0 = 0."""
        a = KnownBits.top(4)
        b = KnownBits.from_constant(4, 0)
        r = transfer_udiv(a, b)
        assert r == KnownBits.from_constant(4, 0)

    def test_udiv_constants(self):
        """10 / 3 = 3."""
        a = KnownBits.from_constant(4, 10)
        b = KnownBits.from_constant(4, 3)
        r = transfer_udiv(a, b)
        assert r.contains(3) and r.num_known_bits() == 4


# ================================================================
#  LLVM Cross-Validation
# ================================================================

class TestCrossValidation:

    def test_cross_validation_json_exists(self):
        """cross_validation.json must exist."""
        assert os.path.exists("/app/cross_validation.json"), \
            "Missing /app/cross_validation.json"

    def test_cross_validation_schema(self):
        """JSON must be an array with entries for all 6 operations."""
        with open("/app/cross_validation.json") as f:
            data = json.load(f)
        assert isinstance(data, list), "cross_validation.json must be a JSON array"
        required_ops = {"add", "sub", "mul", "shl", "lshr", "udiv"}
        found_ops = set()
        for entry in data:
            assert "operation" in entry, "entry missing 'operation'"
            assert "ir_file" in entry, "entry missing 'ir_file'"
            assert "llvm_optimization" in entry, "entry missing 'llvm_optimization'"
            assert "consistent" in entry, "entry missing 'consistent'"
            assert entry["consistent"] is True, \
                f"operation {entry['operation']} marked inconsistent"
            found_ops.add(entry["operation"])
        missing = required_ops - found_ops
        assert not missing, f"Missing operations: {missing}"

    def test_optimized_ir_files_exist(self):
        """Each .ll file must have a corresponding .opt.ll file."""
        originals = glob.glob("/app/ir_testcases/*.ll")
        non_opt = [f for f in originals if not f.endswith(".opt.ll")]
        assert len(non_opt) >= 6, "Expected at least 6 IR test cases"
        for ir_file in non_opt:
            opt_file = ir_file.replace(".ll", ".opt.ll")
            assert os.path.exists(opt_file), f"Missing optimized IR: {opt_file}"

    def test_optimized_ir_is_processed(self):
        """Optimized IR should differ from original (opt adds metadata)."""
        for name in ["add_disjoint", "sub_identity", "mul_power2",
                      "shl_known", "lshr_fold", "udiv_zero"]:
            orig = f"/app/ir_testcases/{name}.ll"
            opt = f"/app/ir_testcases/{name}.opt.ll"
            if os.path.exists(orig) and os.path.exists(opt):
                with open(orig) as f:
                    orig_content = f.read()
                with open(opt) as f:
                    opt_content = f.read()
                assert orig_content != opt_content, \
                    f"{name}.opt.ll appears unprocessed by opt-18"

    def test_opt_tool_produces_expected_output(self):
        """Verify opt-18 correctly optimizes the add_disjoint case."""
        result = subprocess.run(
            ["opt-18", "-passes=instcombine", "-S",
             "/app/ir_testcases/add_disjoint.ll"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"opt-18 failed: {result.stderr}"
        # LLVM should recognize disjoint bits and convert add to or
        # or annotate the add with the 'disjoint' flag
        output = result.stdout
        assert "or i8" in output or "disjoint" in output, \
            "LLVM should optimize add with disjoint bits"


# ================================================================
#  Verification Report
# ================================================================

class TestVerificationReport:

    def test_report_exists(self):
        """verification_results.json must exist."""
        assert os.path.exists("/app/verification_results.json"), \
            "Missing /app/verification_results.json"

    def test_report_schema(self):
        """Report must have correct structure with all ops sound."""
        with open("/app/verification_results.json") as f:
            data = json.load(f)
        required_ops = {"add", "sub", "mul", "shl", "lshr", "udiv"}
        assert set(data.keys()) >= required_ops, \
            f"Missing ops: {required_ops - set(data.keys())}"
        for op in required_ops:
            assert "sound" in data[op], f"{op} missing 'sound'"
            assert "precision" in data[op], f"{op} missing 'precision'"
            assert data[op]["sound"] is True, f"{op} not sound"
            assert isinstance(data[op]["precision"], (int, float)), \
                f"{op} precision not numeric"
