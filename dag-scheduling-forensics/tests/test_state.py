
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone

import pytest


def parse_iso(ts_str):
    """Parse ISO timestamp, handling both Z and +00:00 formats."""
    if ts_str is None:
        return None
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


@pytest.fixture(scope="module")
def run_analyzer():
    """Run the analyzer once before all tests."""
    result = subprocess.run(
        ["python3", "/app/analyzer.py"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"analyzer.py failed with return code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return result


@pytest.fixture(scope="module")
def results(run_analyzer):
    """Load the results JSON produced by the analyzer."""
    path = "/app/results.json"
    assert os.path.exists(path), "results.json was not created"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def db_conn(run_analyzer):
    """Open the SQLite database produced by the analyzer."""
    path = "/app/airflow_forensics.db"
    assert os.path.exists(path), "airflow_forensics.db was not created"
    conn = sqlite3.connect(path)
    yield conn
    conn.close()


# == SQLite Database Tests ==


class TestSQLiteDatabase:
    def test_dags_table_row_count(self, db_conn):
        cur = db_conn.execute("SELECT COUNT(*) FROM dags")
        assert cur.fetchone()[0] == 7

    def test_tasks_table_row_count(self, db_conn):
        cur = db_conn.execute("SELECT COUNT(*) FROM tasks")
        assert cur.fetchone()[0] == 33

    def test_executions_table_row_count(self, db_conn):
        cur = db_conn.execute("SELECT COUNT(*) FROM executions")
        assert cur.fetchone()[0] == 35

    def test_scheduler_events_table_row_count(self, db_conn):
        cur = db_conn.execute("SELECT COUNT(*) FROM scheduler_events")
        assert cur.fetchone()[0] == 33

    def test_dags_have_expected_ids(self, db_conn):
        cur = db_conn.execute("SELECT dag_id FROM dags ORDER BY dag_id")
        dag_ids = [row[0] for row in cur.fetchall()]
        assert dag_ids == [
            "alerts", "data_quality", "data_refresh",
            "etl_ingest", "ml_pipeline", "monitoring", "reporting"
        ]

    def test_tasks_table_has_operator_values(self, db_conn):
        cur = db_conn.execute(
            "SELECT DISTINCT operator FROM tasks ORDER BY operator"
        )
        operators = [row[0] for row in cur.fetchall()]
        assert "ExternalTaskMarker" in operators
        assert "ExternalTaskSensor" in operators
        assert "PythonOperator" in operators
        assert "TriggerDagRunOperator" in operators

    def test_executions_schema_has_required_columns(self, db_conn):
        cur = db_conn.execute("PRAGMA table_info(executions)")
        columns = {row[1] for row in cur.fetchall()}
        required = {"dag_id", "task_id", "run_id", "attempt", "state",
                     "start_time", "end_time", "scheduler_job_id"}
        assert required.issubset(columns), (
            f"Missing columns: {required - columns}"
        )


# == Graphviz Visualization Tests ==


class TestGraphVisualization:
    def test_dot_file_exists(self, run_analyzer):
        assert os.path.exists("/app/dependency_graph.dot"), (
            "dependency_graph.dot was not created"
        )

    def test_dot_file_is_valid_digraph(self, run_analyzer):
        with open("/app/dependency_graph.dot") as f:
            content = f.read()
        assert "digraph" in content
        assert "{" in content and "}" in content

    def test_dot_file_contains_edges(self, run_analyzer):
        with open("/app/dependency_graph.dot") as f:
            content = f.read()
        assert "->" in content, "DOT file must contain directed edges"
        assert "etl_ingest" in content
        assert "data_refresh" in content

    def test_dot_file_highlights_cycle_edges(self, run_analyzer):
        with open("/app/dependency_graph.dot") as f:
            content = f.read().lower()
        has_distinct_style = (
            "red" in content
            or "penwidth" in content
            or "style" in content
            or "color" in content
        )
        assert has_distinct_style, (
            "Cycle edges must have a visually distinct style attribute"
        )

    def test_svg_file_exists_and_nonempty(self, run_analyzer):
        path = "/app/dependency_graph.svg"
        assert os.path.exists(path), "dependency_graph.svg was not created"
        size = os.path.getsize(path)
        assert size > 100, f"SVG file is suspiciously small ({size} bytes)"

    def test_svg_contains_svg_element(self, run_analyzer):
        with open("/app/dependency_graph.svg") as f:
            content = f.read()
        assert "<svg" in content.lower(), "File does not appear to be valid SVG"


# == Dependency Graph Results Tests ==


class TestDependencyGraph:
    def test_etl_ingest_depends_on_data_refresh(self, results):
        graph = results["dependency_graph"]
        assert sorted(graph["etl_ingest"]) == ["data_refresh"]

    def test_reporting_depends_on_etl_ingest_and_alerts(self, results):
        graph = results["dependency_graph"]
        assert sorted(graph["reporting"]) == ["alerts", "etl_ingest"]

    def test_data_quality_depends_on_reporting(self, results):
        graph = results["dependency_graph"]
        assert sorted(graph["data_quality"]) == ["reporting"]

    def test_ml_pipeline_depends_on_data_quality(self, results):
        graph = results["dependency_graph"]
        assert sorted(graph["ml_pipeline"]) == ["data_quality"]

    def test_data_refresh_depends_on_ml_pipeline(self, results):
        graph = results["dependency_graph"]
        assert sorted(graph["data_refresh"]) == ["ml_pipeline"]

    def test_alerts_depends_on_data_refresh(self, results):
        graph = results["dependency_graph"]
        assert sorted(graph["alerts"]) == ["data_refresh"]

    def test_monitoring_has_no_dependencies(self, results):
        graph = results["dependency_graph"]
        assert graph["monitoring"] == []

    def test_trigger_dag_not_treated_as_dependency(self, results):
        graph = results["dependency_graph"]
        assert "data_quality" not in graph.get("etl_ingest", [])
        assert "etl_ingest" not in graph.get("monitoring", [])

    def test_external_task_marker_not_treated_as_dependency(self, results):
        """ExternalTaskMarker in etl_ingest targeting data_quality must NOT
        create a dependency edge for etl_ingest."""
        graph = results["dependency_graph"]
        etl_deps = graph.get("etl_ingest", [])
        assert "data_quality" not in etl_deps, (
            "ExternalTaskMarker should not create a dependency for the "
            "containing DAG — it marks upstream completion, not a wait"
        )


# == Cycle Detection Tests ==


class TestCycleDetection:
    def test_exactly_two_cycles_found(self, results):
        cycles = results["cycles"]
        assert len(cycles) == 2, f"Expected 2 cycles, found {len(cycles)}: {cycles}"

    def test_cycle_node_sets_correct(self, results):
        cycles = results["cycles"]
        cycle_sets = sorted([tuple(sorted(c)) for c in cycles])
        expected = sorted([
            ("alerts", "data_quality", "data_refresh", "ml_pipeline", "reporting"),
            ("data_quality", "data_refresh", "etl_ingest", "ml_pipeline", "reporting"),
        ])
        assert cycle_sets == expected, (
            f"Cycle node sets mismatch.\nExpected: {expected}\nGot: {cycle_sets}"
        )

    def test_monitoring_not_in_any_cycle(self, results):
        for cycle in results["cycles"]:
            assert "monitoring" not in cycle, "monitoring should not be in any cycle"


# == Concurrent Execution Tests ==


class TestConcurrentExecutions:
    def test_count(self, results):
        concurrent = results["anomalies"]["concurrent_executions"]
        assert len(concurrent) == 2, (
            f"Expected 2 concurrent executions, found {len(concurrent)}"
        )

    def test_etl_transform_detected(self, results):
        concurrent = results["anomalies"]["concurrent_executions"]
        matches = [
            c for c in concurrent
            if c["dag_id"] == "etl_ingest" and c["task_id"] == "transform"
        ]
        assert len(matches) == 1, "etl_ingest.transform concurrent execution not found"
        assert sorted(matches[0]["attempts"]) == [1, 2]

    def test_reporting_aggregate_detected(self, results):
        concurrent = results["anomalies"]["concurrent_executions"]
        matches = [
            c for c in concurrent
            if c["dag_id"] == "reporting" and c["task_id"] == "aggregate"
        ]
        assert len(matches) == 1, "reporting.aggregate concurrent execution not found"
        assert sorted(matches[0]["attempts"]) == [1, 2]

    def test_no_false_positive_on_normal_retry(self, results):
        """data_quality.value_check on Jan 14 had a normal retry (no overlap)."""
        concurrent = results["anomalies"]["concurrent_executions"]
        false_positives = [
            c for c in concurrent
            if c["dag_id"] == "data_quality" and c["task_id"] == "value_check"
        ]
        assert len(false_positives) == 0, (
            "False positive: normal retry flagged as concurrent execution"
        )


# == Zombie Task Tests ==


class TestZombieTasks:
    def test_count(self, results):
        zombies = results["anomalies"]["zombie_tasks"]
        assert len(zombies) == 1, f"Expected 1 zombie task, found {len(zombies)}"

    def test_ml_pipeline_train_detected(self, results):
        zombies = results["anomalies"]["zombie_tasks"]
        z = zombies[0]
        assert z["dag_id"] == "ml_pipeline"
        assert z["task_id"] == "train"
        assert z["run_id"] == "scheduled__2024-01-14T00:00:00+00:00"
        assert z["attempt"] == 1
        assert z["scheduler_job_id"] == 8


# == Orphaned Task Tests ==


class TestOrphanedTasks:
    def test_count(self, results):
        orphaned = results["anomalies"]["orphaned_tasks"]
        assert len(orphaned) == 1, f"Expected 1 orphaned task, found {len(orphaned)}"

    def test_data_quality_completeness_check_detected(self, results):
        orphaned = results["anomalies"]["orphaned_tasks"]
        o = orphaned[0]
        assert o["dag_id"] == "data_quality"
        assert o["task_id"] == "completeness_check"
        assert o["run_id"] == "scheduled__2024-01-15T00:00:00+00:00"
        assert o["attempt"] == 1
        assert o["scheduler_job_id"] == 99


# == Anomaly Count Tests ==


class TestAnomalyCount:
    def test_total_is_four(self, results):
        assert results["anomaly_count"] == 4, (
            f"Expected anomaly_count=4, got {results['anomaly_count']}"
        )

    def test_sum_matches(self, results):
        a = results["anomalies"]
        total = (
            len(a["concurrent_executions"])
            + len(a["zombie_tasks"])
            + len(a["orphaned_tasks"])
        )
        assert total == results["anomaly_count"], (
            f"anomaly_count ({results['anomaly_count']}) does not match "
            f"sum of anomaly lists ({total})"
        )


# == Scheduler Timeline Tests ==


class TestSchedulerTimeline:
    def test_has_four_jobs(self, results):
        timeline = results["scheduler_timeline"]
        assert len(timeline) == 4, (
            f"Expected 4 scheduler jobs, found {len(timeline)}"
        )

    def test_job_ids_present(self, results):
        timeline = results["scheduler_timeline"]
        job_ids = sorted(j["job_id"] for j in timeline)
        assert job_ids == [8, 9, 10, 11]

    def test_job8_unresponsive(self, results):
        timeline = results["scheduler_timeline"]
        job8 = next(j for j in timeline if j["job_id"] == 8)
        assert job8["status"] == "unresponsive", (
            f"Job 8 should be unresponsive, got '{job8['status']}'"
        )
        assert job8["heartbeat_count"] == 10
        last_hb = parse_iso(job8["last_heartbeat"])
        assert last_hb == datetime(2024, 1, 14, 7, 30, tzinfo=timezone.utc)
        assert job8["end_time"] is None

    def test_job9_completed(self, results):
        timeline = results["scheduler_timeline"]
        job9 = next(j for j in timeline if j["job_id"] == 9)
        assert job9["status"] == "completed", (
            f"Job 9 should be completed, got '{job9['status']}'"
        )
        assert job9["heartbeat_count"] == 1
        assert job9["end_time"] is not None

    def test_job10_completed(self, results):
        timeline = results["scheduler_timeline"]
        job10 = next(j for j in timeline if j["job_id"] == 10)
        assert job10["status"] == "completed", (
            f"Job 10 should be completed, got '{job10['status']}'"
        )
        assert job10["heartbeat_count"] == 6

    def test_job11_active(self, results):
        timeline = results["scheduler_timeline"]
        job11 = next(j for j in timeline if j["job_id"] == 11)
        assert job11["status"] == "active", (
            f"Job 11 should be active, got '{job11['status']}'"
        )
        assert job11["heartbeat_count"] == 10
        assert job11["end_time"] is None


# == Split-Brain Detection Tests ==


class TestSplitBrain:
    def test_exactly_one_window(self, results):
        windows = results["split_brain_windows"]
        assert len(windows) == 1, (
            f"Expected 1 split-brain window, found {len(windows)}"
        )

    def test_window_involves_jobs_10_and_11(self, results):
        w = results["split_brain_windows"][0]
        assert sorted(w["overlapping_jobs"]) == [10, 11]

    def test_window_duration(self, results):
        w = results["split_brain_windows"][0]
        assert w["duration_seconds"] == 300, (
            f"Expected 300s split-brain window, got {w['duration_seconds']}"
        )

    def test_window_timestamps(self, results):
        w = results["split_brain_windows"][0]
        start = parse_iso(w["window_start"])
        end = parse_iso(w["window_end"])
        assert start == datetime(2024, 1, 15, 1, 20, tzinfo=timezone.utc)
        assert end == datetime(2024, 1, 15, 1, 25, tzinfo=timezone.utc)


# == Root Cause Analysis Tests ==


class TestRootCauseAnalysis:
    def test_count(self, results):
        rca = results["root_cause_analysis"]
        assert len(rca) == 4, f"Expected 4 root cause entries, found {len(rca)}"

    def test_zombie_root_cause(self, results):
        rca = results["root_cause_analysis"]
        zombie = next(
            r for r in rca
            if r["anomaly_type"] == "zombie_task"
            and r["dag_id"] == "ml_pipeline"
        )
        assert zombie["task_id"] == "train"
        assert zombie["root_cause"] == "scheduler_unresponsive"
        assert zombie["causal_scheduler_job_id"] == 8

    def test_concurrent_transform_root_cause(self, results):
        rca = results["root_cause_analysis"]
        entry = next(
            r for r in rca
            if r["anomaly_type"] == "concurrent_execution"
            and r["dag_id"] == "etl_ingest"
        )
        assert entry["task_id"] == "transform"
        assert entry["root_cause"] == "scheduler_failover_overlap"
        assert entry["causal_scheduler_job_id"] is None

    def test_concurrent_aggregate_root_cause(self, results):
        rca = results["root_cause_analysis"]
        entry = next(
            r for r in rca
            if r["anomaly_type"] == "concurrent_execution"
            and r["dag_id"] == "reporting"
        )
        assert entry["task_id"] == "aggregate"
        assert entry["root_cause"] == "premature_retry"
        assert entry["causal_scheduler_job_id"] == 11

    def test_orphaned_root_cause(self, results):
        rca = results["root_cause_analysis"]
        orphan = next(
            r for r in rca if r["anomaly_type"] == "orphaned_task"
        )
        assert orphan["dag_id"] == "data_quality"
        assert orphan["task_id"] == "completeness_check"
        assert orphan["root_cause"] == "unknown_scheduler"
        assert orphan["causal_scheduler_job_id"] == 99


# == Downstream Impact Tests ==


class TestDownstreamImpact:
    def test_zombie_impact(self, results):
        rca = results["root_cause_analysis"]
        zombie = next(r for r in rca if r["anomaly_type"] == "zombie_task")
        assert sorted(zombie["downstream_impact"]) == [
            "alerts", "data_quality", "data_refresh", "etl_ingest", "reporting"
        ]

    def test_orphaned_impact(self, results):
        rca = results["root_cause_analysis"]
        orphan = next(r for r in rca if r["anomaly_type"] == "orphaned_task")
        assert sorted(orphan["downstream_impact"]) == [
            "alerts", "data_refresh", "etl_ingest", "ml_pipeline", "reporting"
        ]

    def test_concurrent_transform_impact(self, results):
        rca = results["root_cause_analysis"]
        entry = next(
            r for r in rca
            if r["anomaly_type"] == "concurrent_execution"
            and r["dag_id"] == "etl_ingest"
        )
        assert sorted(entry["downstream_impact"]) == [
            "alerts", "data_quality", "data_refresh", "ml_pipeline", "reporting"
        ]

    def test_concurrent_aggregate_impact(self, results):
        rca = results["root_cause_analysis"]
        entry = next(
            r for r in rca
            if r["anomaly_type"] == "concurrent_execution"
            and r["dag_id"] == "reporting"
        )
        assert sorted(entry["downstream_impact"]) == [
            "alerts", "data_quality", "data_refresh", "etl_ingest", "ml_pipeline"
        ]

    def test_monitoring_never_in_impact(self, results):
        """monitoring has no dependents, so it should never appear in any
        downstream_impact list."""
        for entry in results["root_cause_analysis"]:
            assert "monitoring" not in entry["downstream_impact"], (
                f"monitoring incorrectly listed in downstream_impact for "
                f"{entry['anomaly_type']} on {entry['dag_id']}.{entry['task_id']}"
            )
