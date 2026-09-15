import json
import os
import pytest


REPORT_PATH = "/app/tuning_report.json"


@pytest.fixture(scope="session")
def report():
    """Load the tuning report JSON."""
    assert os.path.exists(REPORT_PATH), f"Tuning report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


def _normalize(name):
    """Normalize parameter names for flexible comparison."""
    return name.lower().strip().replace(" ", "_").replace("-", "_")


def _find_rec(recs, keyword):
    """Find a recommendation containing keyword in parameter name."""
    for r in recs:
        if keyword in _normalize(r["parameter"]):
            return r
    return None


class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), "tuning_report.json missing"

    def test_report_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_metrics(self, report):
        assert "metrics" in report
        assert isinstance(report["metrics"], dict)

    def test_has_optimal_db_cache(self, report):
        assert "optimal_db_cache_size_mb" in report

    def test_has_optimal_pga(self, report):
        assert "optimal_pga_target_mb" in report

    def test_has_top_wait_events(self, report):
        assert "top_wait_events" in report
        assert isinstance(report["top_wait_events"], list)

    def test_has_recommendations(self, report):
        assert "recommendations" in report
        assert isinstance(report["recommendations"], list)


class TestMetrics:
    """Verify performance metrics computed using Oracle's standard formulas."""

    def test_buffer_cache_hit_ratio(self, report):
        # 1 - (physical_reads_cache / (db_block_gets + consistent_gets))
        # 1 - (63000000 / 225000000) = 0.72
        val = report["metrics"]["buffer_cache_hit_ratio"]
        assert isinstance(val, (int, float))
        assert abs(val - 0.72) < 0.005, f"Expected ~0.72, got {val}"

    def test_library_cache_hit_ratio(self, report):
        # sum(pinhits) / sum(pins) across all namespaces
        # 28747125 / 31000000 = 0.92733...
        val = report["metrics"]["library_cache_hit_ratio"]
        assert isinstance(val, (int, float))
        assert abs(val - 0.9273) < 0.005, f"Expected ~0.9273, got {val}"

    def test_hard_parse_ratio(self, report):
        # parse_count_hard / parse_count_total = 7200000 / 8000000 = 0.90
        val = report["metrics"]["hard_parse_ratio"]
        assert isinstance(val, (int, float))
        assert abs(val - 0.90) < 0.005, f"Expected ~0.90, got {val}"

    def test_in_memory_sort_ratio(self, report):
        # sorts_memory / (sorts_memory + sorts_disk) = 120000 / 150000 = 0.80
        val = report["metrics"]["in_memory_sort_ratio"]
        assert isinstance(val, (int, float))
        assert abs(val - 0.80) < 0.005, f"Expected ~0.80, got {val}"

    def test_pga_cache_hit_pct(self, report):
        # Directly from V$PGASTAT 'cache hit percentage' = 84.1
        val = report["metrics"]["pga_cache_hit_pct"]
        assert isinstance(val, (int, float))
        assert abs(val - 84.1) < 1.0, f"Expected ~84.1, got {val}"

    def test_shared_pool_free_pct(self, report):
        # free_memory / total_shared_pool * 100
        # 12582912 / 268435456 * 100 = 4.6875
        val = report["metrics"]["shared_pool_free_pct"]
        assert isinstance(val, (int, float))
        assert abs(val - 4.6875) < 0.5, f"Expected ~4.6875, got {val}"


class TestAdvisoryOptimal:
    """Verify optimal values derived from advisory view threshold analysis."""

    def test_optimal_db_cache_size(self, report):
        # Smallest size_for_estimate_mb where estd_physical_read_factor <= 0.50
        # 896 MB has factor 0.50
        val = report["optimal_db_cache_size_mb"]
        assert val == 896, f"Expected 896, got {val}"

    def test_optimal_pga_target(self, report):
        # Smallest pga_target_for_estimate_mb where estd_overalloc_count == 0
        # 512 MB has overalloc_count 0
        val = report["optimal_pga_target_mb"]
        assert val == 512, f"Expected 512, got {val}"


class TestWaitEvents:
    """Verify wait event analysis with idle exclusion and correct ordering."""

    def test_at_least_five_events(self, report):
        events = report["top_wait_events"]
        assert len(events) >= 5, f"Expected >= 5 events, got {len(events)}"

    def test_top_event_is_shared_pool_latch(self, report):
        top = report["top_wait_events"][0]
        assert "shared pool" in top["event"].lower(), (
            f"Expected top event to contain 'shared pool', got '{top['event']}'"
        )

    def test_events_descending_order(self, report):
        events = report["top_wait_events"]
        times = [e["time_waited_seconds"] for e in events]
        for i in range(len(times) - 1):
            assert times[i] >= times[i + 1], (
                f"Events not in descending order at position {i}: "
                f"{times[i]} < {times[i + 1]}"
            )

    def test_top_event_time_value(self, report):
        top = report["top_wait_events"][0]
        # 75000000000 microseconds = 75000 seconds
        assert abs(top["time_waited_seconds"] - 75000) < 100, (
            f"Expected ~75000s for top event, got {top['time_waited_seconds']}"
        )

    def test_no_idle_events_in_top(self, report):
        idle_fragments = ["sql*net message from client", "sql*net message to client"]
        for ev in report["top_wait_events"]:
            event_lower = ev["event"].lower()
            for idle in idle_fragments:
                assert idle not in event_lower, (
                    f"Idle event found in top events: {ev['event']}"
                )


class TestRecommendations:
    """Verify parameter recommendations based on diagnostic analysis."""

    def test_at_least_four_recommendations(self, report):
        assert len(report["recommendations"]) >= 4

    def test_has_cursor_sharing(self, report):
        rec = _find_rec(report["recommendations"], "cursor_sharing")
        assert rec is not None, "Missing cursor_sharing recommendation"

    def test_cursor_sharing_recommends_force(self, report):
        rec = _find_rec(report["recommendations"], "cursor_sharing")
        assert rec is not None, "Missing cursor_sharing recommendation"
        assert "force" in rec["recommended_value"].lower(), (
            f"cursor_sharing should recommend FORCE, got {rec['recommended_value']}"
        )

    def test_cursor_sharing_high_priority(self, report):
        rec = _find_rec(report["recommendations"], "cursor_sharing")
        assert rec is not None, "Missing cursor_sharing recommendation"
        assert rec["rank"] <= 2, (
            f"cursor_sharing should be rank 1 or 2 (top priority), got {rec['rank']}"
        )

    def test_has_db_cache_size(self, report):
        rec = _find_rec(report["recommendations"], "db_cache_size")
        assert rec is not None, "Missing db_cache_size recommendation"

    def test_has_pga_aggregate_target(self, report):
        rec = _find_rec(report["recommendations"], "pga_aggregate_target")
        assert rec is not None, "Missing pga_aggregate_target recommendation"

    def test_has_shared_pool_size(self, report):
        rec = _find_rec(report["recommendations"], "shared_pool_size")
        assert rec is not None, "Missing shared_pool_size recommendation"

    def test_recommendations_ranked_ascending(self, report):
        ranks = [r["rank"] for r in report["recommendations"]]
        assert ranks == sorted(ranks), f"Ranks not in ascending order: {ranks}"

    def test_no_duplicate_ranks(self, report):
        ranks = [r["rank"] for r in report["recommendations"]]
        assert len(set(ranks)) == len(ranks), f"Duplicate ranks found: {ranks}"
