"""Tests for the ML Research Integrity Audit Pipeline."""

import json
import os
import subprocess

import pytest

REPORT_PATH = "/app/audit_report.json"


@pytest.fixture(scope="session", autouse=True)
def run_audit():
    """Run the audit tool before all tests."""
    result = subprocess.run(
        ["python3", "/app/audit.py"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"audit.py failed with exit code {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(REPORT_PATH), "audit_report.json was not created"


@pytest.fixture
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# ── Structure tests ──────────────────────────────────────────────────


class TestReportStructure:
    def test_has_experiments(self, report):
        assert "experiments" in report
        assert isinstance(report["experiments"], dict)

    def test_has_summary(self, report):
        assert "summary" in report
        assert isinstance(report["summary"], dict)

    def test_all_experiments_present(self, report):
        expected = {
            "exp-001", "exp-002", "exp-003", "exp-004",
            "exp-005", "exp-006", "exp-007", "exp-008",
        }
        assert set(report["experiments"].keys()) == expected

    def test_experiment_fields(self, report):
        for exp_id, exp in report["experiments"].items():
            assert "verdict" in exp, f"{exp_id} missing 'verdict'"
            assert "metrics" in exp, f"{exp_id} missing 'metrics'"
            assert "violations" in exp, f"{exp_id} missing 'violations'"
            assert exp["verdict"] in ("PASS", "SUSPICIOUS"), (
                f"{exp_id} has invalid verdict: {exp['verdict']}"
            )
            assert isinstance(exp["violations"], list), (
                f"{exp_id} violations should be a list"
            )


# ── Summary tests ────────────────────────────────────────────────────


class TestSummary:
    def test_total_count(self, report):
        assert report["summary"]["total"] == 8

    def test_pass_count(self, report):
        assert report["summary"]["pass"] == 4

    def test_suspicious_count(self, report):
        assert report["summary"]["suspicious"] == 4

    def test_flagged_experiments(self, report):
        flagged = set(report["summary"]["flagged_experiments"])
        assert flagged == {"exp-005", "exp-006", "exp-007", "exp-008"}


# ── Clean experiment tests (text log format) ─────────────────────────


class TestCleanTextLogs:
    def test_exp001_verdict(self, report):
        assert report["experiments"]["exp-001"]["verdict"] == "PASS"

    def test_exp001_accuracy(self, report):
        m = report["experiments"]["exp-001"]["metrics"]
        assert abs(m["final_accuracy"] - 65.23) < 0.5

    def test_exp001_aaa(self, report):
        m = report["experiments"]["exp-001"]["metrics"]
        assert abs(m["final_aaa"] - 72.81) < 0.5

    def test_exp002_verdict(self, report):
        assert report["experiments"]["exp-002"]["verdict"] == "PASS"

    def test_exp002_accuracy(self, report):
        """Must extract from the second (complete) run, not the first."""
        m = report["experiments"]["exp-002"]["metrics"]
        assert abs(m["final_accuracy"] - 62.84) < 0.5

    def test_exp002_aaa(self, report):
        m = report["experiments"]["exp-002"]["metrics"]
        assert abs(m["final_aaa"] - 70.65) < 0.5


# ── Clean experiment tests (HDF5 format) ─────────────────────────────


class TestCleanHDF5:
    def test_exp003_verdict(self, report):
        assert report["experiments"]["exp-003"]["verdict"] == "PASS"

    def test_exp003_accuracy(self, report):
        m = report["experiments"]["exp-003"]["metrics"]
        assert abs(m["final_accuracy"] - 61.42) < 0.5

    def test_exp003_aaa(self, report):
        m = report["experiments"]["exp-003"]["metrics"]
        assert abs(m["final_aaa"] - 69.43) < 0.5


# ── Clean experiment tests (Parquet format) ──────────────────────────


class TestCleanParquet:
    def test_exp004_verdict(self, report):
        assert report["experiments"]["exp-004"]["verdict"] == "PASS"

    def test_exp004_txt_r1(self, report):
        m = report["experiments"]["exp-004"]["metrics"]
        assert abs(m["txt_r1"] - 42.6) < 0.5

    def test_exp004_img_r1(self, report):
        m = report["experiments"]["exp-004"]["metrics"]
        assert abs(m["img_r1"] - 31.2) < 0.5


# ── Fraud detection tests ───────────────────────────────────────────


class TestFraudDetection:
    """Verify each fraud type is correctly identified with proper violation labels."""

    def test_exp005_verdict(self, report):
        assert report["experiments"]["exp-005"]["verdict"] == "SUSPICIOUS"

    def test_exp005_curve_authenticity(self, report):
        """HDF5 training diagnostics reveal fabrication — gradient norms are constant."""
        vtypes = [v["type"] for v in report["experiments"]["exp-005"]["violations"]]
        assert "curve_authenticity" in vtypes

    def test_exp006_verdict(self, report):
        assert report["experiments"]["exp-006"]["verdict"] == "SUSPICIOUS"

    def test_exp006_distribution_conformance(self, report):
        """Parquet score distribution is uniform, inconsistent with reference beta."""
        vtypes = [v["type"] for v in report["experiments"]["exp-006"]["violations"]]
        assert "distribution_conformance" in vtypes

    def test_exp007_verdict(self, report):
        assert report["experiments"]["exp-007"]["verdict"] == "SUSPICIOUS"

    def test_exp007_progression_plausibility(self, report):
        """Text log shows a 68+ point accuracy jump between consecutive stages."""
        vtypes = [v["type"] for v in report["experiments"]["exp-007"]["violations"]]
        assert "progression_plausibility" in vtypes

    def test_exp008_verdict(self, report):
        assert report["experiments"]["exp-008"]["verdict"] == "SUSPICIOUS"

    def test_exp008_artifact_integrity(self, report):
        """Patch file in experiment directory indicates grading tampering."""
        vtypes = [v["type"] for v in report["experiments"]["exp-008"]["violations"]]
        assert "artifact_integrity" in vtypes


# ── False-positive tests ─────────────────────────────────────────────


class TestNoFalsePositives:
    def test_exp001_no_violations(self, report):
        assert len(report["experiments"]["exp-001"]["violations"]) == 0

    def test_exp002_no_violations(self, report):
        assert len(report["experiments"]["exp-002"]["violations"]) == 0

    def test_exp003_no_violations(self, report):
        assert len(report["experiments"]["exp-003"]["violations"]) == 0

    def test_exp004_no_violations(self, report):
        assert len(report["experiments"]["exp-004"]["violations"]) == 0
