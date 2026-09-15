"""Tests for the Flink streaming topology analyzer.

Verifies correctness of optimization report values, Graphviz visualizations,
SQLite analysis database, and Makefile pipeline orchestration across four
execution plan scenarios with distinct topologies.

"""

import json
import re
import sqlite3
import subprocess
import pytest
from pathlib import Path

REPORT_PATH = "/app/output/report.json"
DB_PATH = "/app/output/analysis.db"
PLAN_NAMES = [
    "ecommerce_joins",
    "compliance_pipeline",
    "analytics_pipeline",
    "realtime_dashboard",
]


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Run the optimizer and render visualizations before all tests."""
    result = subprocess.run(
        ["python3", "/app/run_optimizer.py"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Optimizer failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    result = subprocess.run(
        ["make", "-C", "/app", "visualize"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Visualization failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


@pytest.fixture(scope="session")
def report():
    """Load the generated report."""
    assert Path(REPORT_PATH).exists(), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def db_conn():
    """Connect to the analysis database."""
    assert Path(DB_PATH).exists(), f"Database not found at {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()


class TestMakePipeline:
    """Verify that the Makefile pipeline targets work correctly."""

    def test_make_validate_input(self):
        r = subprocess.run(
            ["make", "-C", "/app", "validate-input"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            f"make validate-input failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )

    def test_make_validate_output(self, report):
        r = subprocess.run(
            ["make", "-C", "/app", "validate-output"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            f"make validate-output failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )


class TestReportStructure:
    def test_report_has_plans_key(self, report):
        assert "plans" in report

    def test_report_has_all_plans(self, report):
        plans = report["plans"]
        for name in PLAN_NAMES:
            assert name in plans, f"Missing plan: {name}"

    def test_each_plan_has_required_fields(self, report):
        for plan_name, plan_data in report["plans"].items():
            assert "total_join_state_bytes" in plan_data, (
                f"{plan_name} missing total_join_state_bytes"
            )
            assert "multi_join_opportunities" in plan_data, (
                f"{plan_name} missing multi_join_opportunities"
            )
            assert "async_ml_predict" in plan_data, (
                f"{plan_name} missing async_ml_predict"
            )


class TestEcommerceJoins:
    """Tests for the ecommerce_joins plan.

    4 source streams joined on user_id via 3 cascaded joins
    (2 INNER + 1 LEFT). All share user_id key.
    TTL = 600 seconds.
    """

    def test_total_join_state(self, report):
        plan = report["plans"]["ecommerce_joins"]
        assert plan["total_join_state_bytes"] == 437400000

    def test_has_one_multi_join_opportunity(self, report):
        plan = report["plans"]["ecommerce_joins"]
        assert len(plan["multi_join_opportunities"]) == 1

    def test_multi_join_join_ids(self, report):
        opp = report["plans"]["ecommerce_joins"]["multi_join_opportunities"][0]
        assert sorted(opp["join_ids"]) == [5, 6, 7]

    def test_multi_join_common_key(self, report):
        opp = report["plans"]["ecommerce_joins"]["multi_join_opportunities"][0]
        assert opp["common_key"] == "user_id"

    def test_multi_join_source_ids(self, report):
        opp = report["plans"]["ecommerce_joins"]["multi_join_opportunities"][0]
        assert sorted(opp["source_ids"]) == [1, 2, 3, 4]

    def test_multi_join_cascaded_state(self, report):
        opp = report["plans"]["ecommerce_joins"]["multi_join_opportunities"][0]
        assert opp["cascaded_state_bytes"] == 437400000

    def test_multi_join_optimized_state(self, report):
        opp = report["plans"]["ecommerce_joins"]["multi_join_opportunities"][0]
        assert opp["multi_join_state_bytes"] == 254400000

    def test_multi_join_savings_bytes(self, report):
        opp = report["plans"]["ecommerce_joins"]["multi_join_opportunities"][0]
        assert opp["savings_bytes"] == 183000000

    def test_multi_join_savings_percent(self, report):
        opp = report["plans"]["ecommerce_joins"]["multi_join_opportunities"][0]
        assert abs(opp["savings_percent"] - 41.84) < 0.01

    def test_no_async_ml_predict(self, report):
        plan = report["plans"]["ecommerce_joins"]
        assert len(plan["async_ml_predict"]) == 0


class TestCompliancePipeline:
    """Tests for the compliance_pipeline plan.

    Single join (product_listings INNER JOIN seller_info) feeding into
    AsyncMLPredict. No multi-join opportunity (only 1 join).
    TTL = 900 seconds.
    """

    def test_total_join_state(self, report):
        plan = report["plans"]["compliance_pipeline"]
        assert plan["total_join_state_bytes"] == 253440000

    def test_no_multi_join_opportunities(self, report):
        plan = report["plans"]["compliance_pipeline"]
        assert len(plan["multi_join_opportunities"]) == 0

    def test_has_one_async_ml_predict(self, report):
        plan = report["plans"]["compliance_pipeline"]
        assert len(plan["async_ml_predict"]) == 1

    def test_async_node_id(self, report):
        config = report["plans"]["compliance_pipeline"]["async_ml_predict"][0]
        assert config["node_id"] == 4

    def test_async_name(self, report):
        config = report["plans"]["compliance_pipeline"]["async_ml_predict"][0]
        assert config["name"] == "compliance_check"

    def test_async_queue_depth(self, report):
        config = report["plans"]["compliance_pipeline"]["async_ml_predict"][0]
        assert config["required_queue_depth"] == 720

    def test_async_min_parallelism(self, report):
        config = report["plans"]["compliance_pipeline"]["async_ml_predict"][0]
        assert config["min_parallelism"] == 6

    def test_async_memory_per_subtask(self, report):
        config = report["plans"]["compliance_pipeline"]["async_ml_predict"][0]
        assert config["memory_per_subtask_bytes"] == 262144

    def test_async_total_memory(self, report):
        config = report["plans"]["compliance_pipeline"]["async_ml_predict"][0]
        assert config["total_async_memory_bytes"] == 1474560


class TestAnalyticsPipeline:
    """Tests for the analytics_pipeline plan.

    3 cascaded joins on session_id, BUT join id=6 is FULL OUTER JOIN,
    which blocks multi-join optimization (only INNER/LEFT eligible).
    Plus an AsyncMLPredict node for anomaly detection.
    TTL = 1200 seconds.
    """

    def test_total_join_state(self, report):
        plan = report["plans"]["analytics_pipeline"]
        assert plan["total_join_state_bytes"] == 1615680000

    def test_no_multi_join_full_join_blocks(self, report):
        """FULL join in the chain prevents multi-join optimization."""
        plan = report["plans"]["analytics_pipeline"]
        assert len(plan["multi_join_opportunities"]) == 0

    def test_has_one_async_ml_predict(self, report):
        plan = report["plans"]["analytics_pipeline"]
        assert len(plan["async_ml_predict"]) == 1

    def test_async_node_id_and_name(self, report):
        config = report["plans"]["analytics_pipeline"]["async_ml_predict"][0]
        assert config["node_id"] == 8
        assert config["name"] == "anomaly_detection"

    def test_async_queue_depth(self, report):
        config = report["plans"]["analytics_pipeline"]["async_ml_predict"][0]
        assert config["required_queue_depth"] == 384

    def test_async_min_parallelism(self, report):
        config = report["plans"]["analytics_pipeline"]["async_ml_predict"][0]
        assert config["min_parallelism"] == 6

    def test_async_memory_per_subtask(self, report):
        config = report["plans"]["analytics_pipeline"]["async_ml_predict"][0]
        assert config["memory_per_subtask_bytes"] == 98304

    def test_async_total_memory(self, report):
        config = report["plans"]["analytics_pipeline"]["async_ml_predict"][0]
        assert config["total_async_memory_bytes"] == 589824


class TestRealtimeDashboard:
    """Tests for the realtime_dashboard plan.

    Diamond topology: two independent join sub-chains merge at join id=9.
    Chain 6->7->9: joins 6,7 share page_id (INNER), join 9 uses session_id.
    Chain 8->9: join 8 is RIGHT.
    TTL = 800 seconds.
    """

    def test_total_join_state(self, report):
        plan = report["plans"]["realtime_dashboard"]
        assert plan["total_join_state_bytes"] == 1911680000

    def test_has_one_multi_join_opportunity(self, report):
        plan = report["plans"]["realtime_dashboard"]
        assert len(plan["multi_join_opportunities"]) == 1

    def test_multi_join_join_ids(self, report):
        opp = report["plans"]["realtime_dashboard"]["multi_join_opportunities"][0]
        assert sorted(opp["join_ids"]) == [6, 7]

    def test_multi_join_common_key(self, report):
        opp = report["plans"]["realtime_dashboard"]["multi_join_opportunities"][0]
        assert opp["common_key"] == "page_id"

    def test_multi_join_source_ids(self, report):
        opp = report["plans"]["realtime_dashboard"]["multi_join_opportunities"][0]
        assert sorted(opp["source_ids"]) == [1, 2, 3]

    def test_multi_join_cascaded_state(self, report):
        opp = report["plans"]["realtime_dashboard"]["multi_join_opportunities"][0]
        assert opp["cascaded_state_bytes"] == 1310720000

    def test_multi_join_optimized_state(self, report):
        opp = report["plans"]["realtime_dashboard"]["multi_join_opportunities"][0]
        assert opp["multi_join_state_bytes"] == 696320000

    def test_multi_join_savings_bytes(self, report):
        opp = report["plans"]["realtime_dashboard"]["multi_join_opportunities"][0]
        assert opp["savings_bytes"] == 614400000

    def test_multi_join_savings_percent(self, report):
        opp = report["plans"]["realtime_dashboard"]["multi_join_opportunities"][0]
        assert abs(opp["savings_percent"] - 46.88) < 0.01

    def test_has_one_async_ml_predict(self, report):
        plan = report["plans"]["realtime_dashboard"]
        assert len(plan["async_ml_predict"]) == 1

    def test_async_node_id_and_name(self, report):
        config = report["plans"]["realtime_dashboard"]["async_ml_predict"][0]
        assert config["node_id"] == 10
        assert config["name"] == "ctr_prediction"

    def test_async_queue_depth(self, report):
        config = report["plans"]["realtime_dashboard"]["async_ml_predict"][0]
        assert config["required_queue_depth"] == 480

    def test_async_min_parallelism(self, report):
        config = report["plans"]["realtime_dashboard"]["async_ml_predict"][0]
        assert config["min_parallelism"] == 3

    def test_async_memory_per_subtask(self, report):
        config = report["plans"]["realtime_dashboard"]["async_ml_predict"][0]
        assert config["memory_per_subtask_bytes"] == 819200

    def test_async_total_memory(self, report):
        config = report["plans"]["realtime_dashboard"]["async_ml_predict"][0]
        assert config["total_async_memory_bytes"] == 1966080


class TestVisualization:
    """Tests for Graphviz DOT source and SVG visualizations."""

    def test_dot_files_exist(self):
        for name in PLAN_NAMES:
            assert Path(f"/app/output/{name}.dot").exists(), (
                f"Missing DOT file for {name}"
            )

    def test_svg_files_exist(self):
        for name in PLAN_NAMES:
            assert Path(f"/app/output/{name}.svg").exists(), (
                f"Missing SVG file for {name}"
            )

    def test_svg_files_valid(self):
        for name in PLAN_NAMES:
            content = Path(f"/app/output/{name}.svg").read_text()
            assert "<svg" in content, f"SVG for {name} missing <svg element"

    def test_dot_digraph_format(self):
        for name in PLAN_NAMES:
            dot = Path(f"/app/output/{name}.dot").read_text()
            assert "digraph" in dot, f"DOT for {name} missing digraph"
            assert "->" in dot, f"DOT for {name} missing directed edges"

    def test_dot_ecommerce_nodes(self):
        dot = Path("/app/output/ecommerce_joins.dot").read_text()
        for node_name in ["pageviews", "clicks", "orders", "profiles",
                          "join_pageviews_clicks", "join_with_orders",
                          "join_with_profiles", "output"]:
            assert node_name in dot, f"Missing node {node_name}"

    def test_dot_dashboard_edges(self):
        dot = Path("/app/output/realtime_dashboard.dot").read_text()
        for src, dst in [(1, 6), (2, 6), (4, 8), (5, 8), (7, 9), (8, 9)]:
            assert re.search(rf'{src}\s*->\s*{dst}', dot), (
                f"Missing edge {src} -> {dst}"
            )

    def test_dot_join_types_present(self):
        dot = Path("/app/output/realtime_dashboard.dot").read_text()
        assert "INNER" in dot, "Missing INNER join type label"
        assert "RIGHT" in dot, "Missing RIGHT join type label"
        assert "LEFT" in dot, "Missing LEFT join type label"

    def test_dot_source_rates(self):
        dot = Path("/app/output/compliance_pipeline.dot").read_text()
        assert "500" in dot, "Missing source rate 500"
        assert "100" in dot, "Missing source rate 100"

    def test_dot_async_qps(self):
        dot = Path("/app/output/compliance_pipeline.dot").read_text()
        assert "400" in dot, "Missing async QPS 400"


class TestDatabase:
    """Tests for SQLite analysis database."""

    def test_database_exists(self):
        assert Path(DB_PATH).exists()

    def test_join_state_table_exists(self, db_conn):
        cur = db_conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='join_state'"
        )
        assert cur.fetchone() is not None, "Table join_state does not exist"

    def test_multi_join_table_exists(self, db_conn):
        cur = db_conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='multi_join_opportunities'"
        )
        assert cur.fetchone() is not None

    def test_async_configs_table_exists(self, db_conn):
        cur = db_conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='async_ml_configs'"
        )
        assert cur.fetchone() is not None

    def test_join_state_row_count(self, db_conn):
        cur = db_conn.execute("SELECT COUNT(*) FROM join_state")
        count = cur.fetchone()[0]
        # 3 in ecommerce + 1 in compliance + 3 in analytics + 4 in dashboard
        assert count == 11

    def test_join_state_ecommerce_j5(self, db_conn):
        cur = db_conn.execute(
            "SELECT left_state_bytes, right_state_bytes, total_state_bytes "
            "FROM join_state WHERE plan_name='ecommerce_joins' AND node_id=5"
        )
        row = cur.fetchone()
        assert row is not None, "Missing join_state row for ecommerce_joins node 5"
        assert row[0] == 120000000, f"left_state_bytes: expected 120000000, got {row[0]}"
        assert row[1] == 86400000, f"right_state_bytes: expected 86400000, got {row[1]}"
        assert row[2] == 206400000, f"total_state_bytes: expected 206400000, got {row[2]}"

    def test_join_state_ecommerce_j6(self, db_conn):
        cur = db_conn.execute(
            "SELECT left_state_bytes, right_state_bytes, total_state_bytes "
            "FROM join_state WHERE plan_name='ecommerce_joins' AND node_id=6"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 108000000
        assert row[1] == 36000000
        assert row[2] == 144000000

    def test_join_state_dashboard_j9(self, db_conn):
        cur = db_conn.execute(
            "SELECT left_state_bytes, right_state_bytes, total_state_bytes "
            "FROM join_state WHERE plan_name='realtime_dashboard' AND node_id=9"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 491520000
        assert row[1] == 48000000
        assert row[2] == 539520000

    def test_join_state_plan_totals(self, db_conn):
        for plan_name, expected_total in [
            ("ecommerce_joins", 437400000),
            ("compliance_pipeline", 253440000),
            ("analytics_pipeline", 1615680000),
            ("realtime_dashboard", 1911680000),
        ]:
            cur = db_conn.execute(
                "SELECT SUM(total_state_bytes) FROM join_state "
                "WHERE plan_name=?", (plan_name,)
            )
            total = cur.fetchone()[0]
            assert total == expected_total, (
                f"{plan_name}: expected {expected_total}, got {total}"
            )

    def test_multi_join_opportunities_count(self, db_conn):
        cur = db_conn.execute(
            "SELECT COUNT(*) FROM multi_join_opportunities"
        )
        assert cur.fetchone()[0] == 2

    def test_async_configs_count(self, db_conn):
        cur = db_conn.execute("SELECT COUNT(*) FROM async_ml_configs")
        assert cur.fetchone()[0] == 3

    def test_async_config_compliance(self, db_conn):
        cur = db_conn.execute(
            "SELECT required_queue_depth, min_parallelism, "
            "memory_per_subtask_bytes, total_async_memory_bytes "
            "FROM async_ml_configs WHERE plan_name='compliance_pipeline'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 720
        assert row[1] == 6
        assert row[2] == 262144
        assert row[3] == 1474560

    def test_async_config_dashboard(self, db_conn):
        cur = db_conn.execute(
            "SELECT required_queue_depth, min_parallelism "
            "FROM async_ml_configs WHERE plan_name='realtime_dashboard'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 480
        assert row[1] == 3


class TestCrossValidation:
    """Cross-validation tests ensuring internal consistency of the report."""

    def test_savings_equals_diff(self, report):
        """savings_bytes must equal cascaded_state - multi_join_state."""
        for plan_name, plan_data in report["plans"].items():
            for opp in plan_data["multi_join_opportunities"]:
                expected = opp["cascaded_state_bytes"] - opp["multi_join_state_bytes"]
                assert opp["savings_bytes"] == expected, (
                    f"{plan_name}: savings_bytes mismatch"
                )

    def test_savings_percent_consistent(self, report):
        """savings_percent must match savings_bytes / cascaded_state * 100."""
        for plan_name, plan_data in report["plans"].items():
            for opp in plan_data["multi_join_opportunities"]:
                if opp["cascaded_state_bytes"] > 0:
                    expected_pct = round(
                        opp["savings_bytes"] / opp["cascaded_state_bytes"] * 100, 2
                    )
                    assert abs(opp["savings_percent"] - expected_pct) < 0.01, (
                        f"{plan_name}: savings_percent mismatch"
                    )

    def test_multi_join_state_less_than_cascaded(self, report):
        for plan_name, plan_data in report["plans"].items():
            for opp in plan_data["multi_join_opportunities"]:
                assert opp["multi_join_state_bytes"] < opp["cascaded_state_bytes"]

    def test_queue_depth_positive(self, report):
        for plan_name, plan_data in report["plans"].items():
            for config in plan_data["async_ml_predict"]:
                assert config["required_queue_depth"] > 0

    def test_parallelism_positive(self, report):
        for plan_name, plan_data in report["plans"].items():
            for config in plan_data["async_ml_predict"]:
                assert config["min_parallelism"] > 0

    def test_join_ids_sorted(self, report):
        for plan_name, plan_data in report["plans"].items():
            for opp in plan_data["multi_join_opportunities"]:
                assert opp["join_ids"] == sorted(opp["join_ids"])

    def test_source_ids_sorted(self, report):
        for plan_name, plan_data in report["plans"].items():
            for opp in plan_data["multi_join_opportunities"]:
                assert opp["source_ids"] == sorted(opp["source_ids"])

    def test_report_matches_database(self, report, db_conn):
        """Verify JSON report totals match SQLite database totals."""
        for plan_name, plan_data in report["plans"].items():
            cur = db_conn.execute(
                "SELECT SUM(total_state_bytes) FROM join_state "
                "WHERE plan_name=?", (plan_name,)
            )
            db_total = cur.fetchone()[0]
            if db_total is None:
                db_total = 0
            assert plan_data["total_join_state_bytes"] == db_total, (
                f"{plan_name}: report total {plan_data['total_join_state_bytes']} "
                f"!= DB total {db_total}"
            )
