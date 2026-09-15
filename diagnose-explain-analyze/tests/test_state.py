"""Tests for TiDB EXPLAIN ANALYZE Diagnostic Engine output."""

import json
import os
import sqlite3 as sqlite3_mod
import pytest


@pytest.fixture(scope="module")
def diagnostics():
    path = "/app/output/diagnostics.json"
    assert os.path.isfile(path), f"Output file not found: {path}"
    with open(path, "r") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def db():
    db_path = "/app/output/operators.db"
    assert os.path.isfile(db_path), f"SQLite database not found: {db_path}"
    conn = sqlite3_mod.connect(db_path)
    conn.row_factory = sqlite3_mod.Row
    yield conn
    conn.close()


class TestOutputStructure:
    def test_top_level_keys(self, diagnostics):
        assert "plans" in diagnostics, "Missing 'plans' key"
        assert "concurrency_analysis" in diagnostics, "Missing 'concurrency_analysis' key"
        assert "comparative_analysis" in diagnostics, "Missing 'comparative_analysis' key"

    def test_all_plans_present(self, diagnostics):
        expected = {
            "lock_contention.plan",
            "mvcc_max.plan",
            "mvcc_min.plan",
            "concurrency.plan",
            "hash_join.plan",
        }
        assert expected == set(diagnostics["plans"].keys()), (
            f"Expected plans {expected}, got {set(diagnostics['plans'].keys())}"
        )

    def test_plan_has_required_fields(self, diagnostics):
        for name, plan in diagnostics["plans"].items():
            assert "total_time_ms" in plan, f"{name}: missing total_time_ms"
            assert "bottleneck_operator" in plan, f"{name}: missing bottleneck_operator"
            assert "operators" in plan, f"{name}: missing operators"
            assert "issues" in plan, f"{name}: missing issues"


class TestLockContention:
    def test_total_time(self, diagnostics):
        plan = diagnostics["plans"]["lock_contention.plan"]
        assert abs(plan["total_time_ms"] - 3870.0) < 50, (
            f"Expected ~3870ms, got {plan['total_time_ms']}"
        )

    def test_bottleneck(self, diagnostics):
        plan = diagnostics["plans"]["lock_contention.plan"]
        assert plan["bottleneck_operator"] == "Point_Get_1"

    def test_issue_detected(self, diagnostics):
        plan = diagnostics["plans"]["lock_contention.plan"]
        lock_issues = [i for i in plan["issues"] if i["type"] == "lock_contention"]
        assert len(lock_issues) >= 1, "No lock_contention issue detected"

    def test_issue_operator(self, diagnostics):
        plan = diagnostics["plans"]["lock_contention.plan"]
        lock_issues = [i for i in plan["issues"] if i["type"] == "lock_contention"]
        assert lock_issues[0]["operator"] == "Point_Get_1"

    def test_resolve_lock_time(self, diagnostics):
        plan = diagnostics["plans"]["lock_contention.plan"]
        lock_issues = [i for i in plan["issues"] if i["type"] == "lock_contention"]
        details = lock_issues[0]["details"]
        assert abs(details["resolve_lock_time_ms"] - 3860.0) < 50, (
            f"Expected ~3860ms, got {details['resolve_lock_time_ms']}"
        )

    def test_backoff_count(self, diagnostics):
        plan = diagnostics["plans"]["lock_contention.plan"]
        lock_issues = [i for i in plan["issues"] if i["type"] == "lock_contention"]
        details = lock_issues[0]["details"]
        assert details["backoff_count"] == 18

    def test_operator_count(self, diagnostics):
        plan = diagnostics["plans"]["lock_contention.plan"]
        assert len(plan["operators"]) == 1, (
            f"Expected 1 operator (Point_Get_1), got {len(plan['operators'])}"
        )


class TestMVCCTombstone:
    def test_max_total_time(self, diagnostics):
        plan = diagnostics["plans"]["mvcc_max.plan"]
        assert abs(plan["total_time_ms"] - 3.45) < 1.0, (
            f"Expected ~3.45ms, got {plan['total_time_ms']}"
        )

    def test_min_total_time(self, diagnostics):
        plan = diagnostics["plans"]["mvcc_min.plan"]
        assert abs(plan["total_time_ms"] - 12400.0) < 200, (
            f"Expected ~12400ms, got {plan['total_time_ms']}"
        )

    def test_max_no_tombstone_issue(self, diagnostics):
        """The fast MAX query should NOT trigger a false-positive mvcc_tombstone detection."""
        plan = diagnostics["plans"]["mvcc_max.plan"]
        tombstone_issues = [i for i in plan["issues"] if i["type"] == "mvcc_tombstone"]
        assert len(tombstone_issues) == 0, (
            "False positive: mvcc_max.plan should have no mvcc_tombstone issue"
        )

    def test_min_tombstone_detected(self, diagnostics):
        plan = diagnostics["plans"]["mvcc_min.plan"]
        tombstone_issues = [i for i in plan["issues"] if i["type"] == "mvcc_tombstone"]
        assert len(tombstone_issues) >= 1, (
            "MVCC tombstone issue not detected in mvcc_min.plan"
        )

    def test_min_cop_task_count(self, diagnostics):
        plan = diagnostics["plans"]["mvcc_min.plan"]
        tombstone_issues = [i for i in plan["issues"] if i["type"] == "mvcc_tombstone"]
        assert tombstone_issues[0]["details"]["cop_task_count"] == 238

    def test_min_max_proc_keys(self, diagnostics):
        plan = diagnostics["plans"]["mvcc_min.plan"]
        tombstone_issues = [i for i in plan["issues"] if i["type"] == "mvcc_tombstone"]
        assert tombstone_issues[0]["details"]["max_proc_keys"] == 620000

    def test_max_operator_count(self, diagnostics):
        plan = diagnostics["plans"]["mvcc_max.plan"]
        assert len(plan["operators"]) == 6, (
            f"Expected 6 operators in mvcc_max.plan, got {len(plan['operators'])}"
        )

    def test_min_operator_count(self, diagnostics):
        plan = diagnostics["plans"]["mvcc_min.plan"]
        assert len(plan["operators"]) == 6, (
            f"Expected 6 operators in mvcc_min.plan, got {len(plan['operators'])}"
        )


class TestConcurrency:
    def test_index_task_concurrency(self, diagnostics):
        conc = diagnostics["concurrency_analysis"]["concurrency.plan"]["IndexLookUp_10"]
        assert conc["index_task_concurrency"] == 1, (
            f"index_task concurrency should default to 1, got {conc['index_task_concurrency']}"
        )

    def test_table_task_concurrency(self, diagnostics):
        conc = diagnostics["concurrency_analysis"]["concurrency.plan"]["IndexLookUp_10"]
        assert conc["table_task_concurrency"] == 8, (
            f"Expected table_task concurrency 8, got {conc['table_task_concurrency']}"
        )

    def test_distsql_concurrency(self, diagnostics):
        conc = diagnostics["concurrency_analysis"]["concurrency.plan"]["IndexLookUp_10"]
        assert conc["distsql_concurrency"] == 20, (
            f"Expected distsql_concurrency 20, got {conc['distsql_concurrency']}"
        )

    def test_max_table_cop_tasks(self, diagnostics):
        conc = diagnostics["concurrency_analysis"]["concurrency.plan"]["IndexLookUp_10"]
        assert conc["max_table_cop_tasks"] == 160, (
            f"Expected 160 max table cop tasks, got {conc['max_table_cop_tasks']}"
        )

    def test_operator_count(self, diagnostics):
        plan = diagnostics["plans"]["concurrency.plan"]
        assert len(plan["operators"]) == 3, (
            f"Expected 3 operators in concurrency.plan, got {len(plan['operators'])}"
        )


class TestHashJoin:
    def test_total_time(self, diagnostics):
        plan = diagnostics["plans"]["hash_join.plan"]
        assert abs(plan["total_time_ms"] - 6520.0) < 100, (
            f"Expected ~6520ms, got {plan['total_time_ms']}"
        )

    def test_memory_spill_detected(self, diagnostics):
        plan = diagnostics["plans"]["hash_join.plan"]
        spill_issues = [i for i in plan["issues"] if i["type"] == "memory_spill"]
        assert len(spill_issues) >= 1, "Memory spill not detected in hash_join.plan"

    def test_disk_mb(self, diagnostics):
        plan = diagnostics["plans"]["hash_join.plan"]
        spill_issues = [i for i in plan["issues"] if i["type"] == "memory_spill"]
        assert abs(spill_issues[0]["details"]["disk_mb"] - 245.0) < 5, (
            f"Expected ~245 MB disk spill, got {spill_issues[0]['details']['disk_mb']}"
        )

    def test_suboptimal_join_detected(self, diagnostics):
        plan = diagnostics["plans"]["hash_join.plan"]
        join_issues = [
            i for i in plan["issues"] if i["type"] == "suboptimal_join_order"
        ]
        assert len(join_issues) >= 1, "Suboptimal join order not detected"

    def test_build_side_rows(self, diagnostics):
        plan = diagnostics["plans"]["hash_join.plan"]
        join_issues = [
            i for i in plan["issues"] if i["type"] == "suboptimal_join_order"
        ]
        assert join_issues[0]["details"]["build_side_rows"] == 1180000

    def test_probe_side_rows(self, diagnostics):
        plan = diagnostics["plans"]["hash_join.plan"]
        join_issues = [
            i for i in plan["issues"] if i["type"] == "suboptimal_join_order"
        ]
        assert join_issues[0]["details"]["probe_side_rows"] == 142000

    def test_operator_count(self, diagnostics):
        plan = diagnostics["plans"]["hash_join.plan"]
        assert len(plan["operators"]) == 5, (
            f"Expected 5 operators in hash_join.plan, got {len(plan['operators'])}"
        )


class TestComparativeAnalysis:
    def test_mvcc_comparison_exists(self, diagnostics):
        assert "mvcc_comparison" in diagnostics["comparative_analysis"], (
            "Missing 'mvcc_comparison' in comparative_analysis"
        )

    def test_fast_plan(self, diagnostics):
        comp = diagnostics["comparative_analysis"]["mvcc_comparison"]
        assert comp["fast_plan"] == "mvcc_max.plan"

    def test_slow_plan(self, diagnostics):
        comp = diagnostics["comparative_analysis"]["mvcc_comparison"]
        assert comp["slow_plan"] == "mvcc_min.plan"

    def test_time_ratio(self, diagnostics):
        comp = diagnostics["comparative_analysis"]["mvcc_comparison"]
        assert 3000 < comp["time_ratio"] < 4000, (
            f"Expected time ratio ~3594, got {comp['time_ratio']}"
        )

    def test_root_cause(self, diagnostics):
        comp = diagnostics["comparative_analysis"]["mvcc_comparison"]
        assert comp["root_cause"] == "mvcc_tombstone"


class TestSQLiteDatabase:
    def test_operators_table_exists(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='operators'"
        )
        assert cursor.fetchone() is not None, "operators table not found"

    def test_issues_table_exists(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='issues'"
        )
        assert cursor.fetchone() is not None, "issues table not found"

    def test_operators_columns(self, db):
        cursor = db.execute("PRAGMA table_info(operators)")
        cols = {row[1] for row in cursor.fetchall()}
        expected = {
            "plan_file", "operator_id", "depth", "task_type",
            "est_rows", "act_rows", "time_ms", "self_time_ms",
            "parent_operator_id",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_issues_columns(self, db):
        cursor = db.execute("PRAGMA table_info(issues)")
        cols = {row[1] for row in cursor.fetchall()}
        expected = {"plan_file", "issue_type", "operator_id", "details_json"}
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_operator_count_matches_json(self, db, diagnostics):
        for plan_name, plan_data in diagnostics["plans"].items():
            cursor = db.execute(
                "SELECT COUNT(*) FROM operators WHERE plan_file=?", (plan_name,)
            )
            db_count = cursor.fetchone()[0]
            json_count = len(plan_data["operators"])
            assert db_count == json_count, (
                f"{plan_name}: SQLite has {db_count} operators, JSON has {json_count}"
            )

    def test_issues_count_matches_json(self, db, diagnostics):
        total_json = sum(len(p["issues"]) for p in diagnostics["plans"].values())
        cursor = db.execute("SELECT COUNT(*) FROM issues")
        db_count = cursor.fetchone()[0]
        assert db_count == total_json, (
            f"SQLite has {db_count} issues, JSON has {total_json}"
        )

    def test_lock_contention_issue_in_db(self, db):
        cursor = db.execute(
            "SELECT details_json FROM issues "
            "WHERE plan_file='lock_contention.plan' AND issue_type='lock_contention'"
        )
        row = cursor.fetchone()
        assert row is not None, "lock_contention issue not in SQLite"
        details = json.loads(row[0])
        assert abs(details["resolve_lock_time_ms"] - 3860.0) < 50

    def test_operator_depth_values(self, db):
        cursor = db.execute(
            "SELECT operator_id, depth FROM operators "
            "WHERE plan_file='hash_join.plan' AND depth=0"
        )
        roots = cursor.fetchall()
        assert len(roots) == 1, f"Expected 1 root operator at depth 0, got {len(roots)}"
        assert roots[0][0] == "HashJoin_35"

    def test_parent_relationship(self, db):
        cursor = db.execute(
            "SELECT parent_operator_id FROM operators "
            "WHERE plan_file='lock_contention.plan' AND operator_id='Point_Get_1'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] is None, "Root operator should have NULL parent"


class TestGraphvizOutput:
    PLAN_NAMES = [
        "lock_contention.plan",
        "mvcc_max.plan",
        "mvcc_min.plan",
        "concurrency.plan",
        "hash_join.plan",
    ]

    def test_dot_files_exist(self):
        for plan_name in self.PLAN_NAMES:
            dot_path = f"/app/output/trees/{plan_name}.dot"
            assert os.path.isfile(dot_path), f"DOT file not found: {dot_path}"

    def test_svg_files_exist(self):
        for plan_name in self.PLAN_NAMES:
            svg_path = f"/app/output/trees/{plan_name}.svg"
            assert os.path.isfile(svg_path), f"SVG file not found: {svg_path}"

    def test_dot_contains_operator_ids(self):
        dot_path = "/app/output/trees/lock_contention.plan.dot"
        with open(dot_path) as f:
            content = f.read()
        assert "Point_Get_1" in content, "DOT file missing Point_Get_1 operator"

    def test_dot_contains_task_types(self):
        dot_path = "/app/output/trees/hash_join.plan.dot"
        with open(dot_path) as f:
            content = f.read()
        assert "root" in content, "DOT file missing root task type label"
        assert "cop" in content, "DOT file missing cop task type label"

    def test_dot_has_edges_for_tree(self):
        dot_path = "/app/output/trees/mvcc_min.plan.dot"
        with open(dot_path) as f:
            content = f.read()
        assert "->" in content, "DOT file has no edges (expected parent->child links)"

    def test_svg_valid_markup(self):
        svg_path = "/app/output/trees/lock_contention.plan.svg"
        with open(svg_path) as f:
            content = f.read()
        assert "<svg" in content.lower(), "SVG file does not contain valid SVG markup"

    def test_svg_nonempty(self):
        svg_path = "/app/output/trees/hash_join.plan.svg"
        size = os.path.getsize(svg_path)
        assert size > 100, f"SVG file suspiciously small ({size} bytes)"
