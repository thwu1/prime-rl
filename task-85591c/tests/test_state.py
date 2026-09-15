
import subprocess
import json
import os
import pytest

AUDITOR = "/app/auditor"
RESULTS_DIR = "/app/jepsen-results"


def run_auditor(test_name):
    """Run the auditor on a test directory and return parsed JSON output."""
    test_dir = os.path.join(RESULTS_DIR, test_name)
    result = subprocess.run(
        [AUDITOR, test_dir],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Auditor exited with code {result.returncode} on {test_name}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(f"Auditor output is not valid JSON: {result.stdout!r}")


def validate_dot(dot_string):
    """Validate DOT syntax using the graphviz dot command."""
    if not dot_string:
        return True
    result = subprocess.run(
        ["dot", "-Tcanon"],
        input=dot_string,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


class TestAuditorExecutable:
    """Verify the auditor exists and is executable."""

    def test_auditor_exists(self):
        assert os.path.exists(AUDITOR), f"Auditor not found at {AUDITOR}"

    def test_auditor_is_executable(self):
        assert os.access(AUDITOR, os.X_OK), f"{AUDITOR} is not executable"


class TestOutputFormat:
    """Verify JSON output structure."""

    def test_output_has_required_keys(self):
        out = run_auditor("test-001")
        assert "anomalies" in out, "Output must contain 'anomalies' key"
        assert "isolation_level" in out, "Output must contain 'isolation_level' key"
        assert "cycle_dot" in out, "Output must contain 'cycle_dot' key"

    def test_anomalies_is_list(self):
        out = run_auditor("test-001")
        assert isinstance(out["anomalies"], list)

    def test_isolation_level_is_string(self):
        out = run_auditor("test-001")
        assert isinstance(out["isolation_level"], str)

    def test_cycle_dot_is_string(self):
        out = run_auditor("test-001")
        assert isinstance(out["cycle_dot"], str)


class TestH1Serializable:
    """test-001: Clean history -- no anomalies, serializable."""

    def test_no_anomalies(self):
        out = run_auditor("test-001")
        assert out["anomalies"] == [], f"Expected no anomalies, got {out['anomalies']}"

    def test_serializable(self):
        out = run_auditor("test-001")
        assert out["isolation_level"] == "serializable"

    def test_no_cycles(self):
        out = run_auditor("test-001")
        assert out["cycle_dot"] == ""


class TestH2AbortedRead:
    """test-002: G1a -- committed txn reads data written by aborted txn."""

    def test_detects_g1a(self):
        out = run_auditor("test-002")
        assert "G1a" in out["anomalies"], f"Expected G1a in {out['anomalies']}"

    def test_no_g0(self):
        out = run_auditor("test-002")
        assert "G0" not in out["anomalies"]

    def test_no_cycle_anomalies(self):
        out = run_auditor("test-002")
        for a in ["G1c", "G-single", "G2-item"]:
            assert a not in out["anomalies"], f"Unexpected {a}"

    def test_isolation_read_uncommitted(self):
        out = run_auditor("test-002")
        assert out["isolation_level"] == "read-uncommitted"


class TestH3IntermediateRead:
    """test-003: G1b -- committed txn reads partial state of another txn."""

    def test_detects_g1b(self):
        out = run_auditor("test-003")
        assert "G1b" in out["anomalies"], f"Expected G1b in {out['anomalies']}"

    def test_no_g0_or_g1a(self):
        out = run_auditor("test-003")
        assert "G0" not in out["anomalies"]
        assert "G1a" not in out["anomalies"]

    def test_isolation_read_uncommitted(self):
        out = run_auditor("test-003")
        assert out["isolation_level"] == "read-uncommitted"


class TestH4CircularInfoFlow:
    """test-004: G1c -- cycle of write-read edges (no anti-dependencies)."""

    def test_detects_g1c(self):
        out = run_auditor("test-004")
        assert "G1c" in out["anomalies"], f"Expected G1c in {out['anomalies']}"

    def test_no_g0(self):
        out = run_auditor("test-004")
        assert "G0" not in out["anomalies"]

    def test_no_rw_anomalies(self):
        out = run_auditor("test-004")
        assert "G-single" not in out["anomalies"]
        assert "G2-item" not in out["anomalies"]

    def test_isolation_read_uncommitted(self):
        out = run_auditor("test-004")
        assert out["isolation_level"] == "read-uncommitted"

    def test_dot_has_wr_edges(self):
        out = run_auditor("test-004")
        dot = out["cycle_dot"]
        assert dot != "", "Expected non-empty DOT for G1c cycle"
        assert validate_dot(dot), "DOT syntax is invalid"
        assert "wr" in dot, "DOT should contain wr edge labels"


class TestH5ReadSkew:
    """test-005: G-single -- cycle with exactly one rw edge."""

    def test_detects_g_single(self):
        out = run_auditor("test-005")
        assert "G-single" in out["anomalies"], f"Expected G-single in {out['anomalies']}"

    def test_no_g0_or_g1(self):
        out = run_auditor("test-005")
        for a in ["G0", "G1a", "G1b", "G1c"]:
            assert a not in out["anomalies"], f"Unexpected {a}"

    def test_no_g2_item(self):
        out = run_auditor("test-005")
        assert "G2-item" not in out["anomalies"]

    def test_isolation_read_committed(self):
        out = run_auditor("test-005")
        assert out["isolation_level"] == "read-committed"

    def test_dot_has_rw_edge(self):
        out = run_auditor("test-005")
        dot = out["cycle_dot"]
        assert dot != "", "Expected non-empty DOT for G-single cycle"
        assert validate_dot(dot), "DOT syntax is invalid"
        assert "rw" in dot, "DOT should contain rw edge label"


class TestH6WriteSkew:
    """test-006: G2-item -- cycle with two rw (anti-dependency) edges."""

    def test_detects_g2_item(self):
        out = run_auditor("test-006")
        assert "G2-item" in out["anomalies"], f"Expected G2-item in {out['anomalies']}"

    def test_no_g0_or_g1(self):
        out = run_auditor("test-006")
        for a in ["G0", "G1a", "G1b", "G1c"]:
            assert a not in out["anomalies"], f"Unexpected {a}"

    def test_no_g_single(self):
        out = run_auditor("test-006")
        assert "G-single" not in out["anomalies"]

    def test_isolation_read_committed(self):
        out = run_auditor("test-006")
        assert out["isolation_level"] == "read-committed"

    def test_dot_valid(self):
        out = run_auditor("test-006")
        dot = out["cycle_dot"]
        assert dot != ""
        assert validate_dot(dot)
        assert "rw" in dot


class TestH7DirtyWrite:
    """test-007: G0 -- cycle of write-write dependencies (dirty write).
    This history also uses EDN tagged literals (#inst) that a naive parser
    must handle."""

    def test_detects_g0(self):
        out = run_auditor("test-007")
        assert "G0" in out["anomalies"], f"Expected G0 in {out['anomalies']}"

    def test_no_g1(self):
        out = run_auditor("test-007")
        assert "G1a" not in out["anomalies"]
        assert "G1b" not in out["anomalies"]

    def test_isolation_none(self):
        out = run_auditor("test-007")
        assert out["isolation_level"] == "none"

    def test_dot_has_ww_edges(self):
        out = run_auditor("test-007")
        dot = out["cycle_dot"]
        assert dot != ""
        assert validate_dot(dot)
        assert "ww" in dot


class TestH8MultipleAnomalies:
    """test-008: History with both G1c (wr cycle) and G2-item (rw cycle).
    Also uses EDN tagged literals."""

    def test_detects_g1c(self):
        out = run_auditor("test-008")
        assert "G1c" in out["anomalies"], f"Expected G1c in {out['anomalies']}"

    def test_detects_g2_item(self):
        out = run_auditor("test-008")
        assert "G2-item" in out["anomalies"], f"Expected G2-item in {out['anomalies']}"

    def test_no_g0(self):
        out = run_auditor("test-008")
        assert "G0" not in out["anomalies"]

    def test_isolation_read_uncommitted(self):
        out = run_auditor("test-008")
        assert out["isolation_level"] == "read-uncommitted"

    def test_dot_has_both_edge_types(self):
        out = run_auditor("test-008")
        dot = out["cycle_dot"]
        assert dot != ""
        assert validate_dot(dot)
        assert "wr" in dot, "DOT should contain wr edges (G1c cycle)"
        assert "rw" in dot, "DOT should contain rw edges (G2-item cycle)"


class TestH9LargeCycle:
    """test-009: 4-node G2-item cycle with distractor transactions.
    Also uses EDN tagged literals."""

    def test_detects_g2_item(self):
        out = run_auditor("test-009")
        assert "G2-item" in out["anomalies"], f"Expected G2-item in {out['anomalies']}"

    def test_no_g0_or_g1(self):
        out = run_auditor("test-009")
        for a in ["G0", "G1a", "G1b", "G1c"]:
            assert a not in out["anomalies"], f"Unexpected {a}"

    def test_isolation_read_committed(self):
        out = run_auditor("test-009")
        assert out["isolation_level"] == "read-committed"

    def test_dot_valid_and_has_rw(self):
        out = run_auditor("test-009")
        dot = out["cycle_dot"]
        assert dot != ""
        assert validate_dot(dot)
        assert "rw" in dot
