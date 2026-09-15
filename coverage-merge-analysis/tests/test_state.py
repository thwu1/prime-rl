
import json
import math
import os
import pytest

REPORT_PATH = "/app/coverage_report.json"


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


# --- Summary ----------------------------------------------------------------

class TestSummary:
    def test_total_goals(self, report):
        assert report["summary"]["total_goals"] == 7

    def test_goals_met(self, report):
        assert report["summary"]["goals_met"] == 5

    def test_goals_failed(self, report):
        assert report["summary"]["goals_failed"] == 2

    def test_overall_coverage(self, report):
        # root hierarchical: ~94.19%
        assert math.isclose(
            report["summary"]["overall_coverage_pct"], 94.19, abs_tol=0.5
        )


# --- Code Coverage Metrics ---------------------------------------------------

class TestLineCoverage:
    def test_coverage_pct(self, report):
        m = report["metrics"]["line_coverage"]
        assert math.isclose(m["coverage_pct"], 93.33, abs_tol=0.1)

    def test_counts(self, report):
        m = report["metrics"]["line_coverage"]
        assert m["covered_count"] == 28
        assert m["total_count"] == 30

    def test_goal_not_met(self, report):
        m = report["metrics"]["line_coverage"]
        assert m["goal_met"] is False

    def test_uncovered(self, report):
        m = report["metrics"]["line_coverage"]
        uncovered = set(m["uncovered_items"])
        assert uncovered == {29, 30} or uncovered == {"29", "30"}


class TestBranchCoverage:
    def test_coverage_pct(self, report):
        m = report["metrics"]["branch_coverage"]
        assert math.isclose(m["coverage_pct"], 93.75, abs_tol=0.1)

    def test_counts(self, report):
        m = report["metrics"]["branch_coverage"]
        assert m["covered_count"] == 15
        assert m["total_count"] == 16

    def test_goal_met(self, report):
        m = report["metrics"]["branch_coverage"]
        assert m["goal_met"] is True

    def test_uncovered(self, report):
        m = report["metrics"]["branch_coverage"]
        assert set(m["uncovered_items"]) == {"B16"}


class TestToggleCoverage:
    def test_coverage_pct(self, report):
        m = report["metrics"]["toggle_coverage"]
        # 28/29 = 96.55% (after excluding status[2]_1to0)
        assert math.isclose(m["coverage_pct"], 96.55, abs_tol=0.1)

    def test_counts(self, report):
        m = report["metrics"]["toggle_coverage"]
        assert m["covered_count"] == 28
        assert m["total_count"] == 29

    def test_goal_met(self, report):
        m = report["metrics"]["toggle_coverage"]
        assert m["goal_met"] is True

    def test_uncovered(self, report):
        m = report["metrics"]["toggle_coverage"]
        assert set(m["uncovered_items"]) == {"pkt_data[7]_1to0"}


# --- Functional Coverage Metrics ---------------------------------------------

class TestPacketTypesCoverage:
    """Verification plan leaf 'packet_types' maps to covergroup cg_packet_type."""

    def test_coverage_pct(self, report):
        m = report["metrics"]["packet_types"]
        # cg_packet_type avg: (100 + 100 + 80.645) / 3 = 93.55%
        assert math.isclose(m["coverage_pct"], 93.55, abs_tol=0.1)

    def test_goal_met(self, report):
        m = report["metrics"]["packet_types"]
        assert m["goal_met"] is True


class TestPriorityQosCoverage:
    """Verification plan leaf 'priority_qos' maps to covergroup cg_priority."""

    def test_coverage_pct(self, report):
        m = report["metrics"]["priority_qos"]
        # cg_priority avg: (100 + 100 + 81.25) / 3 = 93.75%
        assert math.isclose(m["coverage_pct"], 93.75, abs_tol=0.1)

    def test_goal_met(self, report):
        m = report["metrics"]["priority_qos"]
        assert m["goal_met"] is True


# --- Covergroup Detail -------------------------------------------------------

class TestCovergroupPacketType:
    def test_cp_pkt_type(self, report):
        c = report["covergroups"]["cg_packet_type"]["components"]["cp_pkt_type"]
        assert c["covered_count"] == 8
        assert c["total_count"] == 8
        assert math.isclose(c["coverage_pct"], 100.0, abs_tol=0.01)

    def test_cp_pkt_size(self, report):
        c = report["covergroups"]["cg_packet_type"]["components"]["cp_pkt_size"]
        assert c["covered_count"] == 4
        assert c["total_count"] == 4
        assert math.isclose(c["coverage_pct"], 100.0, abs_tol=0.01)

    def test_cx_type_x_size(self, report):
        c = report["covergroups"]["cg_packet_type"]["components"]["cx_type_x_size"]
        # 25 covered out of 31 total (32 - 1 excluded ERR:JUMBO)
        assert c["covered_count"] == 25
        assert c["total_count"] == 31
        assert math.isclose(c["coverage_pct"], 80.65, abs_tol=0.1)

    def test_overall_pct(self, report):
        cg = report["covergroups"]["cg_packet_type"]
        assert math.isclose(cg["coverage_pct"], 93.55, abs_tol=0.1)


class TestCovergroupPriority:
    def test_cp_priority(self, report):
        c = report["covergroups"]["cg_priority"]["components"]["cp_priority"]
        assert c["covered_count"] == 4
        assert c["total_count"] == 4

    def test_cp_qos(self, report):
        c = report["covergroups"]["cg_priority"]["components"]["cp_qos"]
        assert c["covered_count"] == 4
        assert c["total_count"] == 4

    def test_cx_priority_x_qos(self, report):
        c = report["covergroups"]["cg_priority"]["components"]["cx_priority_x_qos"]
        assert c["covered_count"] == 13
        assert c["total_count"] == 16
        assert math.isclose(c["coverage_pct"], 81.25, abs_tol=0.1)

    def test_overall_pct(self, report):
        cg = report["covergroups"]["cg_priority"]
        assert math.isclose(cg["coverage_pct"], 93.75, abs_tol=0.1)


# --- FSM Coverage ------------------------------------------------------------

class TestFsmStateCoverage:
    def test_coverage_pct(self, report):
        m = report["metrics"]["state_coverage"]
        # All 6 non-excluded states hit -> 100%
        assert math.isclose(m["coverage_pct"], 100.0, abs_tol=0.01)

    def test_counts(self, report):
        m = report["metrics"]["state_coverage"]
        assert m["covered_count"] == 6
        assert m["total_count"] == 6

    def test_goal_met(self, report):
        m = report["metrics"]["state_coverage"]
        assert m["goal_met"] is True


class TestFsmTransitionCoverage:
    def test_coverage_pct(self, report):
        m = report["metrics"]["transition_coverage"]
        # 8/9 = 88.89% (after excluding ERROR-related transitions)
        assert math.isclose(m["coverage_pct"], 88.89, abs_tol=0.1)

    def test_counts(self, report):
        m = report["metrics"]["transition_coverage"]
        assert m["covered_count"] == 8
        assert m["total_count"] == 9

    def test_goal_not_met(self, report):
        m = report["metrics"]["transition_coverage"]
        assert m["goal_met"] is False

    def test_uncovered(self, report):
        m = report["metrics"]["transition_coverage"]
        assert set(m["uncovered_items"]) == {"RETRY->DROP"}


# --- Hierarchical Coverage ---------------------------------------------------

class TestHierarchy:
    def test_code_quality(self, report):
        h = report["hierarchy"]["code_quality"]
        # (93.33*40 + 93.75*35 + 96.55*25)/100 = 94.28%
        assert math.isclose(h["coverage_pct"], 94.28, abs_tol=0.5)

    def test_functional_verification(self, report):
        h = report["hierarchy"]["functional_verification"]
        # (93.55*50 + 93.75*50)/100 = 93.65%
        assert math.isclose(h["coverage_pct"], 93.65, abs_tol=0.5)

    def test_fsm_verification(self, report):
        h = report["hierarchy"]["fsm_verification"]
        # (100*60 + 88.89*40)/100 = 95.56%
        assert math.isclose(h["coverage_pct"], 95.56, abs_tol=0.5)

    def test_root(self, report):
        h = report["hierarchy"]["packet_router_vplan"]
        # (94.28*40 + 93.65*45 + 95.56*15)/100 = 94.19%
        assert math.isclose(h["coverage_pct"], 94.19, abs_tol=0.5)


# --- Failed Goals ------------------------------------------------------------

class TestFailedGoals:
    def test_count(self, report):
        assert len(report["failed_goals"]) == 2

    def test_line_coverage_failed(self, report):
        failed_metrics = {fg["metric"] for fg in report["failed_goals"]}
        assert "line_coverage" in failed_metrics

    def test_transition_coverage_failed(self, report):
        failed_metrics = {fg["metric"] for fg in report["failed_goals"]}
        assert "transition_coverage" in failed_metrics

    def test_line_gap(self, report):
        for fg in report["failed_goals"]:
            if fg["metric"] == "line_coverage":
                assert math.isclose(fg["goal_pct"], 95.0, abs_tol=0.01)
                assert math.isclose(fg["achieved_pct"], 93.33, abs_tol=0.1)
                assert math.isclose(fg["gap_pct"], 1.67, abs_tol=0.2)

    def test_transition_gap(self, report):
        for fg in report["failed_goals"]:
            if fg["metric"] == "transition_coverage":
                assert math.isclose(fg["goal_pct"], 90.0, abs_tol=0.01)
                assert math.isclose(fg["achieved_pct"], 88.89, abs_tol=0.2)
                assert math.isclose(fg["gap_pct"], 1.11, abs_tol=0.2)


# --- Cross-coverage Uncovered Items ------------------------------------------

class TestCrossCoverageHoles:
    """Verify that uncovered cross bins are correctly identified."""

    def test_cx_type_x_size_uncovered(self, report):
        """After excluding ERR:JUMBO, 6 bins should remain uncovered."""
        cg = report["covergroups"]["cg_packet_type"]["components"]["cx_type_x_size"]
        total = cg["total_count"]
        covered = cg["covered_count"]
        assert total - covered == 6

    def test_cx_priority_x_qos_uncovered(self, report):
        """3 cross bins should be uncovered."""
        cg = report["covergroups"]["cg_priority"]["components"]["cx_priority_x_qos"]
        total = cg["total_count"]
        covered = cg["covered_count"]
        assert total - covered == 3
