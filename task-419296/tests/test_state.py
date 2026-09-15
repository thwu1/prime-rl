import json
import os
import math
import pytest


REPORTS_DIR = "/app/reports"


def load_report(case_name):
    path = os.path.join(REPORTS_DIR, f"{case_name}.json")
    assert os.path.exists(path), f"Report {path} does not exist"
    with open(path) as f:
        return json.load(f)


class TestCase1LockContention:
    """Verify diagnosis of a point query suffering from lock contention."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report("case1")

    def test_bottleneck_operator(self):
        assert self.report["bottleneck_operator"] == "Point_Get_1"

    def test_root_cause(self):
        assert self.report["root_cause"] == "lock_contention"

    def test_self_time(self):
        assert math.isclose(self.report["self_time_ms"], 3180.0, rel_tol=0.05)

    def test_resolve_lock_time(self):
        assert math.isclose(self.report["resolve_lock_time_ms"], 3170.0, rel_tol=0.05)

    def test_get_time(self):
        assert math.isclose(self.report["get_time_ms"], 1.8, rel_tol=0.1)

    def test_backoff_retries(self):
        assert self.report["backoff_retries"] == 15


class TestCase2Concurrency:
    """Verify concurrency analysis for an IndexLookUp query."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report("case2")

    def test_bottleneck_operator(self):
        assert self.report["bottleneck_operator"] == "IndexLookUp_10"

    def test_index_task_concurrency(self):
        assert self.report["index_task_concurrency"] == 1

    def test_table_task_concurrency(self):
        assert self.report["table_task_concurrency"] == 5

    def test_index_distsql_concurrency(self):
        assert self.report["index_distsql_concurrency"] == 15

    def test_table_distsql_concurrency(self):
        assert self.report["table_distsql_concurrency"] == 15

    def test_max_concurrent_cop_tasks(self):
        assert self.report["max_concurrent_cop_tasks"] == 75

    def test_index_cop_estimated_time(self):
        assert math.isclose(
            self.report["index_cop_estimated_time_ms"], 0.1584, rel_tol=0.05
        )

    def test_table_cop_estimated_time(self):
        assert math.isclose(
            self.report["table_cop_estimated_time_ms"], 0.3248, rel_tol=0.05
        )


class TestCase3MVCCTombstone:
    """Verify diagnosis of MVCC tombstone asymmetry between MAX and MIN queries."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report("case3")

    def test_bottleneck_operator(self):
        assert self.report["bottleneck_operator"] == "IndexReader_28"

    def test_root_cause(self):
        assert self.report["root_cause"] == "mvcc_tombstone"

    def test_max_cop_tasks(self):
        assert self.report["max_query"]["cop_tasks"] == 1

    def test_max_proc_keys(self):
        assert self.report["max_query"]["proc_keys"] == 48

    def test_max_scan_order(self):
        assert self.report["max_query"]["scan_order"] == "desc"

    def test_min_cop_tasks(self):
        assert self.report["min_query"]["cop_tasks"] == 210

    def test_min_max_proc_keys(self):
        assert self.report["min_query"]["max_proc_keys"] == 525000

    def test_min_scan_order(self):
        assert self.report["min_query"]["scan_order"] == "asc"

    def test_min_estimated_cop_time(self):
        assert math.isclose(
            self.report["min_query"]["estimated_cop_time_ms"], 9651.88, rel_tol=0.01
        )

    def test_cop_task_ratio(self):
        assert math.isclose(self.report["cop_task_ratio"], 210.0, rel_tol=0.01)

    def test_proc_keys_ratio(self):
        assert math.isclose(self.report["proc_keys_ratio"], 10937.5, rel_tol=0.01)

    def test_gc_tombstone_keys_cleaned(self):
        assert self.report["gc_tombstone_keys_cleaned"] == 892341

    def test_max_store_sst_count(self):
        assert self.report["max_store_sst_count"] == 184532


class TestCase4ComplexJoin:
    """Verify analysis of a multi-operator HashJoin query."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report("case4")

    def test_bottleneck_operator(self):
        assert self.report["bottleneck_operator"] == "IndexLookUp_35"

    def test_hashjoin_self_time(self):
        assert math.isclose(self.report["hashjoin_self_time_ms"], 30.0, rel_tol=0.1)

    def test_table_reader_cop_estimated_time(self):
        assert math.isclose(
            self.report["table_reader_cop_estimated_time_ms"], 2.56, rel_tol=0.05
        )

    def test_probe_cop_estimated_time(self):
        assert math.isclose(
            self.report["probe_cop_estimated_time_ms"], 14.24, rel_tol=0.05
        )

    def test_indexlookup_max_concurrent_cop(self):
        assert self.report["indexlookup_max_concurrent_cop"] == 75

    def test_operators_count(self):
        assert len(self.report["operators"]) >= 5


class TestTriageSummary:
    """Verify cross-incident risk evaluation and root cause classification."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.report = load_report("triage_summary")

    def test_priority_ranking(self):
        assert self.report["priority_ranking"] == [
            "INC-003", "INC-001", "INC-004", "INC-002"
        ]

    def test_gc_related_incidents(self):
        assert sorted(self.report["root_cause_groups"]["gc_related"]) == [
            "INC-001", "INC-003"
        ]

    def test_concurrency_related_incidents(self):
        assert sorted(self.report["root_cause_groups"]["concurrency_related"]) == [
            "INC-002", "INC-004"
        ]

    def test_stores_above_90pct(self):
        assert self.report["cluster_risk_metrics"]["stores_above_90pct_usage"] == 2

    def test_min_available_storage(self):
        assert math.isclose(
            self.report["cluster_risk_metrics"]["min_available_storage_gb"],
            0.33, rel_tol=0.05
        )

    def test_gc_tombstone_ratio(self):
        assert math.isclose(
            self.report["cluster_risk_metrics"]["gc_tombstone_ratio"],
            0.4894, rel_tol=0.05
        )

    def test_max_sst_file_count(self):
        assert self.report["cluster_risk_metrics"]["max_sst_file_count"] == 184532

    def test_total_pending_compaction(self):
        assert self.report["cluster_risk_metrics"]["total_pending_compaction_mb"] == 5887

    def test_gc_related_latency(self):
        assert math.isclose(
            self.report["impact_assessment"]["gc_related_total_latency_ms"],
            12714.0, rel_tol=0.01
        )

    def test_concurrency_related_latency(self):
        assert math.isclose(
            self.report["impact_assessment"]["concurrency_related_total_latency_ms"],
            289.21, rel_tol=0.01
        )

    def test_highest_impact_category(self):
        assert self.report["impact_assessment"]["highest_impact_category"] == "gc_related"

    def test_gc_urgency(self):
        assert self.report["impact_assessment"]["gc_urgency"] == "high"

    def test_storage_urgency(self):
        assert self.report["impact_assessment"]["storage_urgency"] == "critical"
