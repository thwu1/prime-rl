
import json
import os

import pytest

REPORT_PATH = "/app/triage_report.json"


@pytest.fixture(scope="session")
def report():
    assert os.path.exists(REPORT_PATH), f"Triage report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# ── Classifications ────────────────────────────────────────────────────


class TestClassifications:
    def test_classifications_key_exists(self, report):
        assert "classifications" in report

    def test_plan_1_lock_contention(self, report):
        assert report["classifications"]["1"] == "lock_contention"

    def test_plan_2_concurrency_bottleneck(self, report):
        assert report["classifications"]["2"] == "concurrency_bottleneck"

    def test_plan_3_healthy(self, report):
        assert report["classifications"]["3"] == "healthy"

    def test_plan_4_mvcc_tombstone_scan(self, report):
        assert report["classifications"]["4"] == "mvcc_tombstone_scan"

    def test_all_four_plans_classified(self, report):
        for pid in ("1", "2", "3", "4"):
            assert pid in report["classifications"]


# ── Remediations: lock_contention (plan 1) ─────────────────────────────


class TestRemediationsPlan1:
    def test_plan_1_in_remediations(self, report):
        assert "1" in report["top_remediations"]

    def test_plan_1_strategy_order(self, report):
        strats = [r["strategy"] for r in report["top_remediations"]["1"]]
        assert strats == [
            "reduce_transaction_scope",
            "pessimistic_lock_timeout",
            "application_retry_backoff",
        ]

    def test_plan_1_effectiveness_values(self, report):
        effs = [r["avg_effectiveness"] for r in report["top_remediations"]["1"]]
        # reduce_transaction_scope: (68+62+71+58+65)/5 = 64.8
        assert effs[0] == pytest.approx(64.8, abs=0.5)
        # pessimistic_lock_timeout: (42+48+38+52)/4 = 45.0
        assert effs[1] == pytest.approx(45.0, abs=0.5)
        # application_retry_backoff: (28+35+25)/3 = 29.333
        assert effs[2] == pytest.approx(29.33, abs=0.5)


# ── Remediations: concurrency_bottleneck (plan 2) ──────────────────────


class TestRemediationsPlan2:
    def test_plan_2_in_remediations(self, report):
        assert "2" in report["top_remediations"]

    def test_plan_2_strategy_order(self, report):
        strats = [r["strategy"] for r in report["top_remediations"]["2"]]
        assert strats == [
            "increase_executor_concurrency",
            "add_covering_index",
            "split_hot_region",
        ]

    def test_plan_2_effectiveness_values(self, report):
        effs = [r["avg_effectiveness"] for r in report["top_remediations"]["2"]]
        # increase_executor_concurrency: (65+58+72+48)/4 = 60.75
        assert effs[0] == pytest.approx(60.75, abs=0.5)
        # add_covering_index: (52+55+42)/3 = 49.667
        assert effs[1] == pytest.approx(49.67, abs=0.5)
        # split_hot_region: (38+32+35)/3 = 35.0
        assert effs[2] == pytest.approx(35.0, abs=0.5)


# ── Remediations: mvcc_tombstone_scan (plan 4) ─────────────────────────


class TestRemediationsPlan4:
    def test_plan_4_in_remediations(self, report):
        assert "4" in report["top_remediations"]

    def test_plan_4_strategy_order(self, report):
        strats = [r["strategy"] for r in report["top_remediations"]["4"]]
        assert strats == [
            "trigger_manual_gc",
            "reduce_gc_lifetime",
            "compaction_filter_enable",
        ]

    def test_plan_4_effectiveness_values(self, report):
        effs = [r["avg_effectiveness"] for r in report["top_remediations"]["4"]]
        # trigger_manual_gc: (88+82+92+78)/4 = 85.0
        assert effs[0] == pytest.approx(85.0, abs=0.5)
        # reduce_gc_lifetime: (72+68+75+65)/4 = 70.0
        assert effs[1] == pytest.approx(70.0, abs=0.5)
        # compaction_filter_enable: (55+62+48)/3 = 55.0
        assert effs[2] == pytest.approx(55.0, abs=0.5)


# ── Healthy plan excluded from remediations ────────────────────────────


class TestHealthyExcluded:
    def test_plan_3_not_in_remediations(self, report):
        assert "3" not in report["top_remediations"]


# ── Correlated plans ───────────────────────────────────────────────────


class TestCorrelations:
    def test_correlated_plans_key_exists(self, report):
        assert "correlated_plans" in report

    def test_correlated_plans_contains_3_and_4(self, report):
        cp = sorted(report["correlated_plans"])
        assert 3 in cp and 4 in cp

    def test_shared_root_cause(self, report):
        assert report["shared_root_cause"] == "mvcc_tombstone_scan"
