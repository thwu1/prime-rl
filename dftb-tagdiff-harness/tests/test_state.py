"""
Tests for the DFTB+ tagdiff shell implementation and harness.
"""

import gzip
import json
import os
import subprocess
import tempfile

import pytest

TAGDIFF = "/app/tagdiff.sh"
HARNESS = "/app/harness.sh"
TESTCASES = "/app/testcases"
CONF = "/app/tagdiff.conf"
RESULTS_JSON = "/app/results.json"
DETAIL_LOG = "/app/detail.log"


def run_tagdiff(ref, new, configs=None):
    """Run tagdiff.sh and return (exit_code, stdout, stderr)."""
    cmd = [TAGDIFF]
    if configs:
        for c in configs:
            cmd.extend(["-c", c])
    else:
        cmd.extend(["-c", CONF])
    cmd.extend([ref, new])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout, result.stderr


def output_lines(stdout):
    """Return non-empty output lines."""
    return [l for l in stdout.strip().split("\n") if l.strip()]


def status_of(stdout, entry_name):
    """Return the verdict field for *entry_name* (last token on its line)."""
    for line in output_lines(stdout):
        if line.strip().startswith(entry_name):
            parts = line.split()
            if parts:
                return parts[-1]
    return None


def count_entry(stdout, entry_name):
    """Count how many result lines start with *entry_name*."""
    return sum(1 for l in output_lines(stdout) if l.strip().startswith(entry_name))


def run_case(name):
    """Run tagdiff.sh on a testcase directory with proper config chaining."""
    d = os.path.join(TESTCASES, name)
    ref = os.path.join(d, "_autotest.tag")
    new = os.path.join(d, "autotest.tag")
    cfgs = []
    local = os.path.join(d, "tagdiff.conf")
    if os.path.isfile(local):
        cfgs.append(local)
    cfgs.append(CONF)
    return run_tagdiff(ref, new, cfgs)


# ---------------------------------------------------------------------------
# Script existence / permissions
# ---------------------------------------------------------------------------
class TestSetup:
    def test_tagdiff_exists_and_executable(self):
        assert os.path.isfile(TAGDIFF) and os.access(TAGDIFF, os.X_OK)

    def test_harness_exists_and_executable(self):
        assert os.path.isfile(HARNESS) and os.access(HARNESS, os.X_OK)


# ---------------------------------------------------------------------------
# case_all_ok: everything within tolerance
# ---------------------------------------------------------------------------
class TestAllOk:
    def test_exit_zero(self):
        rc, _, _ = run_case("case_all_ok")
        assert rc == 0

    def test_no_duplicate_lines(self):
        _, out, _ = run_case("case_all_ok")
        lines = output_lines(out)
        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}:\n{out}"

    def test_each_entry_ok(self):
        _, out, _ = run_case("case_all_ok")
        assert status_of(out, "orbital_charges") == "OK"
        assert status_of(out, "forces") == "OK"
        assert status_of(out, "mermin_energy") == "OK"


# ---------------------------------------------------------------------------
# case_fail_tol: forces exceeds tolerance
# ---------------------------------------------------------------------------
class TestFailTol:
    def test_exit_nonzero(self):
        rc, out, _ = run_case("case_fail_tol")
        assert rc != 0, f"Expected non-zero exit\n{out}"

    def test_forces_failed(self):
        _, out, _ = run_case("case_fail_tol")
        assert status_of(out, "forces") == "Failed"

    def test_forces_not_duplicated(self):
        _, out, _ = run_case("case_fail_tol")
        assert count_entry(out, "forces") == 1

    def test_others_ok(self):
        _, out, _ = run_case("case_fail_tol")
        assert status_of(out, "orbital_charges") == "OK"
        assert status_of(out, "mermin_energy") == "OK"


# ---------------------------------------------------------------------------
# case_missing: entry absent from new file
# ---------------------------------------------------------------------------
class TestMissing:
    def test_exit_zero(self):
        rc, out, _ = run_case("case_missing")
        assert rc == 0, f"Skipped should not cause failure\n{out}"

    def test_forces_skipped(self):
        _, out, _ = run_case("case_missing")
        assert status_of(out, "forces") == "Skipped"

    def test_present_entries_ok(self):
        _, out, _ = run_case("case_missing")
        assert status_of(out, "orbital_charges") == "OK"
        assert status_of(out, "mermin_energy") == "OK"


# ---------------------------------------------------------------------------
# case_shape_err: shape mismatch
# ---------------------------------------------------------------------------
class TestShapeErr:
    def test_exit_nonzero(self):
        rc, _, _ = run_case("case_shape_err")
        assert rc != 0

    def test_forces_error(self):
        _, out, _ = run_case("case_shape_err")
        assert status_of(out, "forces") == "Error"

    def test_forces_not_duplicated(self):
        _, out, _ = run_case("case_shape_err")
        assert count_entry(out, "forces") == 1


# ---------------------------------------------------------------------------
# case_integer: integer value mismatch
# ---------------------------------------------------------------------------
class TestInteger:
    def test_exit_nonzero(self):
        rc, _, _ = run_case("case_integer")
        assert rc != 0

    def test_num_atoms_failed(self):
        _, out, _ = run_case("case_integer")
        assert status_of(out, "num_atoms") == "Failed"


# ---------------------------------------------------------------------------
# case_logical: logical value mismatch
# ---------------------------------------------------------------------------
class TestLogical:
    def test_exit_nonzero(self):
        rc, out, _ = run_case("case_logical")
        assert rc != 0, f"Logical mismatch should fail\n{out}"

    def test_converged_ok(self):
        _, out, _ = run_case("case_logical")
        assert status_of(out, "converged") == "OK"

    def test_spin_config_failed(self):
        _, out, _ = run_case("case_logical")
        assert status_of(out, "spin_config") == "Failed"


# ---------------------------------------------------------------------------
# case_vector: local config with vector:3 method
# ---------------------------------------------------------------------------
class TestVector:
    def test_exit_zero(self):
        rc, out, _ = run_case("case_vector")
        assert rc == 0, f"Vector comparison should pass\n{out}"

    def test_forces_ok(self):
        _, out, _ = run_case("case_vector")
        assert status_of(out, "forces") == "OK"

    def test_no_duplicates(self):
        _, out, _ = run_case("case_vector")
        lines = output_lines(out)
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}:\n{out}"


# ---------------------------------------------------------------------------
# Complex number comparison (dynamic temp-file tests)
# ---------------------------------------------------------------------------
class TestComplex:
    """Complex values must be compared as paired (re,im) modulus."""

    def _make_complex_files(self):
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("dipole              :complex:1:2\n")
        ref.write("  1.000000000000000E+000  0.000000000000000E+000"
                   "  0.000000000000000E+000  1.000000000000000E+000\n")
        ref.close()

        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("dipole              :complex:1:2\n")
        new.write("  1.000400000000000E+000  3.000000000000000E-004"
                   "  4.000000000000000E-004  1.000000000000000E+000\n")
        new.close()
        # Correct complex diffs:
        #   pair1 sqrt(0.0004^2+0.0003^2) = 5e-4
        #   pair2 sqrt(0.0004^2+0^2)      = 4e-4
        #   max = 5e-4
        return ref.name, new.name

    def test_complex_fails_tight_tolerance(self):
        rp, np = self._make_complex_files()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("dipole: @ 4.5e-4\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(rp, np, [cfg.name])
            assert rc != 0, f"Complex diff 5e-4 > 4.5e-4 should fail\n{out}"
            assert status_of(out, "dipole") == "Failed"
        finally:
            os.unlink(rp); os.unlink(np); os.unlink(cfg.name)

    def test_complex_passes_loose_tolerance(self):
        rp, np = self._make_complex_files()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("dipole: @ 6.0e-4\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(rp, np, [cfg.name])
            assert rc == 0, f"Complex diff 5e-4 <= 6e-4 should pass\n{out}"
            assert status_of(out, "dipole") == "OK"
        finally:
            os.unlink(rp); os.unlink(np); os.unlink(cfg.name)


# ---------------------------------------------------------------------------
# Vector norm comparison (dynamic temp-file tests)
# ---------------------------------------------------------------------------
class TestVectorNorm:
    """Vector method must use Euclidean norm, not raw element diff."""

    def test_vector_exceeds_tolerance(self):
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("forces:real:1:6\n")
        ref.write("  1.0  0.0  0.0  0.0  1.0  0.0\n")
        ref.close()

        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("forces:real:1:6\n")
        new.write("  1.03  0.04  0.0  0.0  1.03  0.04\n")
        new.close()
        # vector:3 groups: norm(0.03,0.04,0)=0.05, norm(0,0.03,0.04)=0.05
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("forces: @ 0.04 @ vector:3\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc != 0, f"Vector norm 0.05 > 0.04 should fail\n{out}"
            assert status_of(out, "forces") == "Failed"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)

    def test_vector_within_tolerance(self):
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("forces:real:1:6\n")
        ref.write("  1.0  0.0  0.0  0.0  1.0  0.0\n")
        ref.close()

        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("forces:real:1:6\n")
        new.write("  1.03  0.04  0.0  0.0  1.03  0.04\n")
        new.close()

        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("forces: @ 0.06 @ vector:3\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc == 0, f"Vector norm 0.05 <= 0.06 should pass\n{out}"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)


# ---------------------------------------------------------------------------
# Keep / nokeep semantics (dynamic temp-file tests)
# ---------------------------------------------------------------------------
class TestKeepNokeep:
    def test_nokeep_consumes(self):
        """Default nokeep: entry matched once and consumed."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("alpha:real:0:\n  1.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("alpha:real:0:\n  1.5\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("alpha: @ 1.0\n.*:real: @ 0.1\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            lines = output_lines(out)
            assert len(lines) == 1, f"Nokeep: expected 1 line, got {len(lines)}:\n{out}"
            assert rc == 0
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)

    def test_keep_allows_rematch(self):
        """Explicit keep: entry remains for subsequent rules."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("alpha:real:0:\n  1.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("alpha:real:0:\n  1.5\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("alpha: @ 1.0 @ element @ keep\n.*:real: @ 0.1\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            lines = output_lines(out)
            assert len(lines) == 2, f"Keep: expected 2 lines, got {len(lines)}:\n{out}"
            assert rc != 0  # second match fails
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)


# ---------------------------------------------------------------------------
# Multiple config files
# ---------------------------------------------------------------------------
class TestMultiConfig:
    def test_first_config_consumes(self):
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("alpha:real:0:\n  1.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("alpha:real:0:\n  1.001\n")
        new.close()
        cfg1 = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg1.write("alpha: @ 1.0e-4\n")  # diff 0.001 > 1e-4 -> Failed, consumed
        cfg1.close()
        cfg2 = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg2.write("alpha: @ 0.01\n")  # alpha already consumed -> no match
        cfg2.close()
        try:
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg1.name, cfg2.name])
            lines = output_lines(out)
            assert len(lines) == 1
            assert status_of(out, "alpha") == "Failed"
            assert rc != 0
        finally:
            os.unlink(ref.name); os.unlink(new.name)
            os.unlink(cfg1.name); os.unlink(cfg2.name)


# ---------------------------------------------------------------------------
# Tolerance boundary
# ---------------------------------------------------------------------------
class TestToleranceBoundary:
    def test_diff_equals_tolerance_passes(self):
        """When diff == tolerance exactly, result must be OK (<= not <)."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("val:real:0:\n  1.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("val:real:0:\n  1.5\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("val: @ 0.5\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc == 0, f"diff == tol should pass (<= comparison)\n{out}"
            assert status_of(out, "val") == "OK"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestErrors:
    def test_missing_ref_file(self):
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("x: @ 1.0\n"); cfg.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("x:real:0:\n  1.0\n"); new.close()
        try:
            rc, _, _ = run_tagdiff("/nonexistent.tag", new.name, [cfg.name])
            assert rc != 0
        finally:
            os.unlink(new.name); os.unlink(cfg.name)

    def test_missing_config(self):
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("x:real:0:\n  1.0\n"); ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("x:real:0:\n  1.0\n"); new.close()
        try:
            rc, _, _ = run_tagdiff(ref.name, new.name, ["/nonexistent.conf"])
            assert rc != 0
        finally:
            os.unlink(ref.name); os.unlink(new.name)


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------
class TestFormat:
    def test_verdict_column(self):
        _, out, _ = run_case("case_all_ok")
        for line in output_lines(out):
            parts = line.split()
            assert parts[-1] in ("OK", "Failed", "Skipped", "Error"), \
                f"Bad verdict '{parts[-1]}' in: {line}"

    def test_method_column(self):
        _, out, _ = run_case("case_all_ok")
        for line in output_lines(out):
            parts = line.split()
            assert parts[1].startswith("element") or parts[1].startswith("vector"), \
                f"Bad method '{parts[1]}' in: {line}"


# ---------------------------------------------------------------------------
# Relative tolerance (dynamic temp-file tests)
# ---------------------------------------------------------------------------
class TestRelativeTolerance:
    """Relative tolerance (rtol) extends comparison to allow proportional differences."""

    def test_rtol_passes_when_atol_fails(self):
        """With rtol, large values can have proportionally larger absolute differences."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("energy:real:0:\n  1000.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("energy:real:0:\n  1001.0\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("energy: @ 0.1 @ element @ nokeep @ rtol:0.002\n")
        cfg.close()
        try:
            # diff=1.0, atol=0.1 fails alone
            # rtol threshold = 0.002 * 1000 = 2.0
            # max(0.1, 2.0) = 2.0, diff=1.0 <= 2.0 -> OK
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc == 0, f"rtol should save this: diff=1.0 <= max(0.1, 2.0)\n{out}"
            assert status_of(out, "energy") == "OK"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)

    def test_rtol_fails_when_both_exceeded(self):
        """Fails when diff exceeds both absolute and relative tolerance."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("energy:real:0:\n  100.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("energy:real:0:\n  101.0\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("energy: @ 0.1 @ element @ nokeep @ rtol:0.005\n")
        cfg.close()
        try:
            # diff=1.0, atol=0.1, rtol_threshold=0.005*100=0.5
            # max(0.1, 0.5)=0.5, diff=1.0 > 0.5 -> Failed
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc != 0, f"Both atol and rtol exceeded, should fail\n{out}"
            assert status_of(out, "energy") == "Failed"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)

    def test_rtol_with_zero_reference(self):
        """When reference magnitude is zero, only absolute tolerance applies."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("val:real:0:\n  0.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("val:real:0:\n  0.05\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("val: @ 0.01 @ element @ nokeep @ rtol:0.1\n")
        cfg.close()
        try:
            # diff=0.05, magnitude=0, rtol_threshold=0.1*0=0
            # max(0.01, 0)=0.01, diff=0.05 > 0.01 -> Failed
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc != 0, f"ref=0 means rtol threshold=0, only atol applies\n{out}"
            assert status_of(out, "val") == "Failed"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)

    def test_rtol_with_multiple_values(self):
        """Magnitude uses max absolute value across all reference values."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("coords:real:1:4\n  -500.0  200.0  100.0  800.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("coords:real:1:4\n  -499.0  200.5  100.2  800.3\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("coords: @ 0.1 @ element @ nokeep @ rtol:0.002\n")
        cfg.close()
        try:
            # max element diff = 1.0 (first element: |-500-(-499)| = 1)
            # magnitude = max(500, 200, 100, 800) = 800
            # rtol_threshold = 0.002 * 800 = 1.6
            # max(0.1, 1.6) = 1.6, diff=1.0 <= 1.6 -> OK
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc == 0, f"rtol with max_mag=800: threshold=1.6 >= diff=1.0\n{out}"
            assert status_of(out, "coords") == "OK"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)

    def test_rtol_does_not_add_to_atol(self):
        """Effective tolerance is max(atol, rtol*mag), NOT atol + rtol*mag."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("val:real:0:\n  100.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("val:real:0:\n  105.05\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("val: @ 5.0 @ element @ nokeep @ rtol:0.001\n")
        cfg.close()
        try:
            # diff = 5.05
            # magnitude = 100, rtol_threshold = 0.001 * 100 = 0.1
            # Correct: max(5.0, 0.1) = 5.0, diff=5.05 > 5.0 -> Failed
            # Wrong (sum): 5.0 + 0.1 = 5.1, diff=5.05 <= 5.1 -> OK
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc != 0, f"diff=5.05 > max(5.0, 0.1)=5.0 should fail\n{out}"
            assert status_of(out, "val") == "Failed"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)


# ---------------------------------------------------------------------------
# Relative tolerance with short form (rtol in field 4, no keep/nokeep)
# ---------------------------------------------------------------------------
class TestRtolShortForm:
    """When keep/nokeep is omitted and field 4 is rtol:VALUE, it must be parsed as rtol."""

    def test_rtol_in_field4(self):
        """rtol without explicit keep/nokeep: field 4 is rtol."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("energy:real:0:\n  1000.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("energy:real:0:\n  1001.0\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        # No keep/nokeep field — rtol in position 4
        cfg.write("energy: @ 0.1 @ element @ rtol:0.002\n")
        cfg.close()
        try:
            # diff=1.0, atol=0.1
            # rtol=0.002, mag=1000, rtol_threshold=2.0
            # max(0.1, 2.0) = 2.0, diff=1.0 <= 2.0 -> OK
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc == 0, f"rtol in field 4 should work: diff=1.0 <= max(0.1, 2.0)\n{out}"
            assert status_of(out, "energy") == "OK"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)

    def test_rtol_field4_nokeep_default(self):
        """rtol in field 4: default keep is nokeep (entry consumed after match)."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("alpha:real:0:\n  100.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("alpha:real:0:\n  100.5\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        # rtol in field 4 (no keep/nokeep), then a catch-all rule
        cfg.write("alpha: @ 0.1 @ element @ rtol:0.01\n")
        cfg.write(".*:real: @ 0.01\n")
        cfg.close()
        try:
            # alpha matched by first rule, consumed (nokeep default)
            # diff=0.5, atol=0.1, rtol=0.01*100=1.0, max(0.1,1.0)=1.0
            # diff=0.5 <= 1.0 -> OK, consumed
            # second rule: alpha already consumed, no match
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            lines = output_lines(out)
            assert len(lines) == 1, f"Entry should be consumed (nokeep default with rtol in field 4): got {len(lines)} lines\n{out}"
            assert rc == 0
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)

    def test_rtol_field4_fails_correctly(self):
        """rtol in field 4: failure when both atol and rtol exceeded."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("val:real:0:\n  50.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("val:real:0:\n  55.0\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        # rtol in field 4, no explicit keep/nokeep
        cfg.write("val: @ 1.0 @ element @ rtol:0.01\n")
        cfg.close()
        try:
            # diff=5.0, atol=1.0, rtol=0.01*50=0.5
            # max(1.0, 0.5)=1.0, diff=5.0 > 1.0 -> Failed
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg.name])
            assert rc != 0, f"diff=5.0 > max(1.0, 0.5)=1.0 should fail\n{out}"
            assert status_of(out, "val") == "Failed"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg.name)


# ---------------------------------------------------------------------------
# Gzipped file support (dynamic temp-file tests)
# ---------------------------------------------------------------------------
class TestGzip:
    """tagdiff.sh must transparently decompress .gz input files."""

    def _create_gz_tag(self, content):
        """Create a gzipped tag file and return its path."""
        f = tempfile.NamedTemporaryFile(suffix=".tag.gz", delete=False)
        f.close()
        with gzip.open(f.name, "wt") as gz:
            gz.write(content)
        return f.name

    def _create_gz_conf(self, content):
        """Create a gzipped config file and return its path."""
        f = tempfile.NamedTemporaryFile(suffix=".conf.gz", delete=False)
        f.close()
        with gzip.open(f.name, "wt") as gz:
            gz.write(content)
        return f.name

    def test_gz_ref_file(self):
        """Gzipped reference file should be transparently decompressed."""
        ref_gz = self._create_gz_tag("val:real:0:\n  1.0\n")
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("val:real:0:\n  1.0\n")
        new.close()
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("val: @ 0.1\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(ref_gz, new.name, [cfg.name])
            assert rc == 0, f"Gzipped ref file should work\n{out}"
            assert status_of(out, "val") == "OK"
        finally:
            os.unlink(ref_gz); os.unlink(new.name); os.unlink(cfg.name)

    def test_gz_new_file(self):
        """Gzipped new file should be transparently decompressed."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("val:real:0:\n  1.0\n")
        ref.close()
        new_gz = self._create_gz_tag("val:real:0:\n  1.0\n")
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("val: @ 0.1\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(ref.name, new_gz, [cfg.name])
            assert rc == 0, f"Gzipped new file should work\n{out}"
            assert status_of(out, "val") == "OK"
        finally:
            os.unlink(ref.name); os.unlink(new_gz); os.unlink(cfg.name)

    def test_gz_config_file(self):
        """Gzipped config file should be transparently decompressed."""
        ref = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        ref.write("val:real:0:\n  1.0\n")
        ref.close()
        new = tempfile.NamedTemporaryFile(mode="w", suffix=".tag", delete=False)
        new.write("val:real:0:\n  1.5\n")
        new.close()
        cfg_gz = self._create_gz_conf("val: @ 1.0\n")
        try:
            rc, out, _ = run_tagdiff(ref.name, new.name, [cfg_gz])
            assert rc == 0, f"Gzipped config file should work\n{out}"
            assert status_of(out, "val") == "OK"
        finally:
            os.unlink(ref.name); os.unlink(new.name); os.unlink(cfg_gz)

    def test_gz_both_tag_files(self):
        """Both ref and new gzipped should work together."""
        ref_gz = self._create_gz_tag("val:real:0:\n  1.0\n")
        new_gz = self._create_gz_tag("val:real:0:\n  1.5\n")
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("val: @ 1.0\n")
        cfg.close()
        try:
            rc, out, _ = run_tagdiff(ref_gz, new_gz, [cfg.name])
            assert rc == 0, f"Both gzipped should work\n{out}"
            assert status_of(out, "val") == "OK"
        finally:
            os.unlink(ref_gz); os.unlink(new_gz); os.unlink(cfg.name)

    def test_gz_with_tolerance_check(self):
        """Gzipped files should produce correct diff values for tolerance checking."""
        ref_gz = self._create_gz_tag("forces:real:1:3\n  1.0  0.0  0.0\n")
        new_gz = self._create_gz_tag("forces:real:1:3\n  1.001  0.0  0.0\n")
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        cfg.write("forces: @ 1.0e-4\n")
        cfg.close()
        try:
            # diff=0.001, tol=0.0001 -> Failed
            rc, out, _ = run_tagdiff(ref_gz, new_gz, [cfg.name])
            assert rc != 0, f"Gzipped: diff=0.001 > tol=0.0001 should fail\n{out}"
            assert status_of(out, "forces") == "Failed"
        finally:
            os.unlink(ref_gz); os.unlink(new_gz); os.unlink(cfg.name)


# ---------------------------------------------------------------------------
# End-to-end harness
# ---------------------------------------------------------------------------
class TestHarness:
    @classmethod
    def setup_class(cls):
        if os.path.exists(RESULTS_JSON):
            os.unlink(RESULTS_JSON)
        cls.result = subprocess.run(
            [HARNESS], capture_output=True, text=True, timeout=120
        )

    def test_json_exists(self):
        assert os.path.isfile(RESULTS_JSON), "harness must write results.json"

    def test_json_schema(self):
        with open(RESULTS_JSON) as f:
            data = json.load(f)
        for key in ("passed", "failed", "total"):
            assert key in data
            assert isinstance(data[key], int)
        assert data["total"] == data["passed"] + data["failed"]

    def test_correct_counts(self):
        with open(RESULTS_JSON) as f:
            data = json.load(f)
        # case_all_ok=PASS, case_missing=PASS, case_vector=PASS
        # case_fail_tol=FAIL, case_shape_err=FAIL, case_integer=FAIL, case_logical=FAIL
        assert data["passed"] == 3, f"Expected 3 passed, got {data['passed']}"
        assert data["failed"] == 4, f"Expected 4 failed, got {data['failed']}"
        assert data["total"] == 7, f"Expected 7 total, got {data['total']}"

    def test_exit_nonzero(self):
        assert self.result.returncode != 0, "harness should exit non-zero when tests fail"


# ---------------------------------------------------------------------------
# Harness detail log
# ---------------------------------------------------------------------------
class TestHarnessDetailLog:
    @classmethod
    def setup_class(cls):
        if os.path.exists(DETAIL_LOG):
            os.unlink(DETAIL_LOG)
        cls.result = subprocess.run(
            [HARNESS], capture_output=True, text=True, timeout=120
        )

    def test_detail_log_exists(self):
        assert os.path.isfile(DETAIL_LOG), "harness must write detail.log"

    def test_detail_log_line_count(self):
        with open(DETAIL_LOG) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        assert len(lines) == 7, f"Expected 7 lines in detail.log, got {len(lines)}"

    def test_detail_log_format(self):
        with open(DETAIL_LOG) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        for line in lines:
            parts = line.split()
            assert len(parts) == 2, f"Expected 'name STATUS', got: {line}"
            assert parts[1] in ("PASS", "FAIL"), f"Bad status in: {line}"

    def test_detail_log_content(self):
        with open(DETAIL_LOG) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        log_dict = {}
        for line in lines:
            parts = line.split()
            log_dict[parts[0]] = parts[1]
        assert log_dict.get("case_all_ok") == "PASS"
        assert log_dict.get("case_fail_tol") == "FAIL"
        assert log_dict.get("case_missing") == "PASS"
        assert log_dict.get("case_shape_err") == "FAIL"
        assert log_dict.get("case_integer") == "FAIL"
        assert log_dict.get("case_logical") == "FAIL"
        assert log_dict.get("case_vector") == "PASS"

    def test_detail_log_sorted(self):
        with open(DETAIL_LOG) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        names = [l.split()[0] for l in lines]
        assert names == sorted(names), \
            f"detail.log entries must be alphabetically sorted, got: {names}"
