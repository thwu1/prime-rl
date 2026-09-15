
import json
import os
import subprocess

import pytest

REPORT_PATH = "/app/analysis_report.json"


@pytest.fixture(scope="session", autouse=True)
def run_analyzer():
    """Run the analyzer before all tests to generate the report."""
    result = subprocess.run(
        ["python3", "/app/analyzer.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Analyzer failed with exit code {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


def normalize_cycle(cycle):
    """Normalize a cycle for order-independent comparison.

    Removes the trailing closing element (if it duplicates the first),
    then rotates so the lexicographically smallest element comes first.
    """
    core = list(cycle)
    if len(core) >= 2 and core[0] == core[-1]:
        core = core[:-1]
    if not core:
        return tuple()
    min_idx = core.index(min(core))
    rotated = core[min_idx:] + core[:min_idx]
    return tuple(rotated)


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------


class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH)

    def test_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_keys(self, report):
        required = {
            "dataset_dependency_cycles",
            "pool_bottlenecks",
            "observed_pool_saturation",
            "total_dags",
            "total_datasets",
        }
        missing = required - set(report.keys())
        assert not missing, f"Missing keys in report: {missing}"


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    # Expected cycle 1: the long cycle through orders_raw
    CYCLE_1 = (
        "data_corrections",
        "orders_raw",
        "orders_clean",
        "feature_store",
        "model_artifact",
        "user_scores",
    )
    CYCLE_1_DAGS = {
        "transform_orders",
        "feature_engineering",
        "train_model",
        "scoring",
        "quality_monitor",
        "data_remediation",
    }

    # Expected cycle 2: the shorter cycle through quality_alerts
    CYCLE_2 = (
        "feature_store",
        "model_artifact",
        "user_scores",
        "quality_alerts",
    )
    CYCLE_2_DAGS = {
        "auto_retrain",
        "train_model",
        "scoring",
        "quality_monitor",
    }

    def test_exactly_two_cycles(self, report):
        cycles = report["dataset_dependency_cycles"]
        assert len(cycles) == 2, (
            f"Expected exactly 2 cycles, found {len(cycles)}"
        )

    def test_cycle_through_orders_raw_datasets(self, report):
        """The 6-dataset cycle through orders_raw must be present."""
        found = {normalize_cycle(c["cycle"]) for c in report["dataset_dependency_cycles"]}
        assert self.CYCLE_1 in found, (
            f"Expected cycle {self.CYCLE_1} not found. Got: {found}"
        )

    def test_cycle_through_quality_alerts_datasets(self, report):
        """The 4-dataset cycle through quality_alerts must be present."""
        found = {normalize_cycle(c["cycle"]) for c in report["dataset_dependency_cycles"]}
        assert self.CYCLE_2 in found, (
            f"Expected cycle {self.CYCLE_2} not found. Got: {found}"
        )

    def test_cycle_through_orders_raw_dags(self, report):
        """Verify correct DAG set for the orders_raw cycle."""
        for c in report["dataset_dependency_cycles"]:
            if normalize_cycle(c["cycle"]) == self.CYCLE_1:
                assert set(c["involved_dags"]) == self.CYCLE_1_DAGS
                return
        pytest.fail("Cycle through orders_raw not found")

    def test_cycle_through_quality_alerts_dags(self, report):
        """Verify correct DAG set for the quality_alerts cycle."""
        for c in report["dataset_dependency_cycles"]:
            if normalize_cycle(c["cycle"]) == self.CYCLE_2:
                assert set(c["involved_dags"]) == self.CYCLE_2_DAGS
                return
        pytest.fail("Cycle through quality_alerts not found")


# ---------------------------------------------------------------------------
# Pool bottleneck analysis (theoretical)
# ---------------------------------------------------------------------------


class TestPoolBottlenecks:
    def _get(self, report, pool_name):
        for b in report["pool_bottlenecks"]:
            if b["pool"] == pool_name:
                return b
        return None

    def test_exactly_three_bottlenecks(self, report):
        n = len(report["pool_bottlenecks"])
        assert n == 3, f"Expected 3 pool bottlenecks, found {n}"

    def test_io_pool_capacity(self, report):
        b = self._get(report, "io_pool")
        assert b is not None, "io_pool bottleneck missing"
        assert b["capacity"] == 8

    def test_io_pool_demand(self, report):
        b = self._get(report, "io_pool")
        assert b is not None
        assert b["max_concurrent_demand"] == 11

    def test_io_pool_dags(self, report):
        b = self._get(report, "io_pool")
        assert b is not None
        expected = {"ingest_orders", "ingest_events", "reporting", "data_remediation"}
        assert set(b["contributing_dags"]) == expected

    def test_compute_pool_capacity(self, report):
        b = self._get(report, "compute_pool")
        assert b is not None, "compute_pool bottleneck missing"
        assert b["capacity"] == 12

    def test_compute_pool_demand(self, report):
        b = self._get(report, "compute_pool")
        assert b is not None
        assert b["max_concurrent_demand"] == 15

    def test_compute_pool_dags(self, report):
        b = self._get(report, "compute_pool")
        assert b is not None
        expected = {
            "transform_orders",
            "transform_events",
            "feature_engineering",
            "quality_monitor",
        }
        assert set(b["contributing_dags"]) == expected

    def test_ml_pool_capacity(self, report):
        b = self._get(report, "ml_pool")
        assert b is not None, "ml_pool bottleneck missing"
        assert b["capacity"] == 4

    def test_ml_pool_demand(self, report):
        b = self._get(report, "ml_pool")
        assert b is not None
        assert b["max_concurrent_demand"] == 7

    def test_ml_pool_dags(self, report):
        b = self._get(report, "ml_pool")
        assert b is not None
        expected = {"train_model", "scoring", "auto_retrain"}
        assert set(b["contributing_dags"]) == expected


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------


class TestStatistics:
    def test_total_dags(self, report):
        assert report["total_dags"] == 11

    def test_total_datasets(self, report):
        assert report["total_datasets"] == 10


# ---------------------------------------------------------------------------
# Parallel-task discrimination
# ---------------------------------------------------------------------------


class TestParallelTaskHandling:
    """Ensure the solution correctly handles concurrent task slot demand."""

    def test_compute_pool_not_naive_max(self, report):
        """compute_pool demand must be 15, not 13.

        quality_monitor has two independent tasks (check_data_quality at 2 slots
        and check_model_drift at 2 slots) that can run concurrently.  A correct
        analysis accounts for their combined demand of 4; a naive approach
        yields only 2, giving 13 total.
        """
        b = next(
            (b for b in report["pool_bottlenecks"] if b["pool"] == "compute_pool"),
            None,
        )
        assert b is not None
        assert b["max_concurrent_demand"] != 13, (
            "Got 13 — parallel task demand was likely underestimated"
        )
        assert b["max_concurrent_demand"] == 15


# ---------------------------------------------------------------------------
# Observed pool saturation (from execution history)
# ---------------------------------------------------------------------------


class TestObservedSaturation:
    """Validate analysis of historical task execution data from metadata.db."""

    def _get(self, report, pool_name):
        for s in report["observed_pool_saturation"]:
            if s["pool"] == pool_name:
                return s
        return None

    def test_exactly_three_saturation_events(self, report):
        n = len(report["observed_pool_saturation"])
        assert n == 3, f"Expected 3 pool saturation events, found {n}"

    def test_io_pool_observed_capacity(self, report):
        s = self._get(report, "io_pool")
        assert s is not None, "io_pool saturation missing"
        assert s["capacity"] == 8

    def test_io_pool_observed_peak(self, report):
        s = self._get(report, "io_pool")
        assert s is not None
        assert s["peak_concurrent_slots"] == 9

    def test_io_pool_observed_dags(self, report):
        s = self._get(report, "io_pool")
        assert s is not None
        expected = {"ingest_events", "ingest_orders", "reporting"}
        assert set(s["contributing_dags"]) == expected

    def test_compute_pool_observed_capacity(self, report):
        s = self._get(report, "compute_pool")
        assert s is not None, "compute_pool saturation missing"
        assert s["capacity"] == 12

    def test_compute_pool_observed_peak(self, report):
        s = self._get(report, "compute_pool")
        assert s is not None
        assert s["peak_concurrent_slots"] == 13

    def test_compute_pool_observed_dags(self, report):
        s = self._get(report, "compute_pool")
        assert s is not None
        expected = {
            "feature_engineering",
            "quality_monitor",
            "transform_events",
            "transform_orders",
        }
        assert set(s["contributing_dags"]) == expected

    def test_ml_pool_observed_capacity(self, report):
        s = self._get(report, "ml_pool")
        assert s is not None, "ml_pool saturation missing"
        assert s["capacity"] == 4

    def test_ml_pool_observed_peak(self, report):
        s = self._get(report, "ml_pool")
        assert s is not None
        assert s["peak_concurrent_slots"] == 6

    def test_ml_pool_observed_dags(self, report):
        s = self._get(report, "ml_pool")
        assert s is not None
        expected = {"scoring", "train_model"}
        assert set(s["contributing_dags"]) == expected

    def test_default_pool_not_saturated(self, report):
        """default_pool has no executions and should not appear."""
        s = self._get(report, "default_pool")
        assert s is None, "default_pool should not be in saturation list"

    def test_observed_ml_pool_excludes_auto_retrain(self, report):
        """auto_retrain contributes to theoretical ml_pool demand but ran at
        a different time window, so it must NOT appear in observed peak."""
        s = self._get(report, "ml_pool")
        assert s is not None
        assert "auto_retrain" not in s["contributing_dags"], (
            "auto_retrain was not running during observed peak saturation"
        )

    def test_observed_vs_theoretical_compute_pool(self, report):
        """Observed peak (13) should differ from theoretical worst-case (15)."""
        theoretical = next(
            (b for b in report["pool_bottlenecks"] if b["pool"] == "compute_pool"),
            None,
        )
        observed = self._get(report, "compute_pool")
        assert theoretical is not None
        assert observed is not None
        assert observed["peak_concurrent_slots"] < theoretical["max_concurrent_demand"], (
            "Observed peak should be less than theoretical worst-case for compute_pool"
        )
