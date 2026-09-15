
import json
import os
import re
import sqlite3
import subprocess
import pytest


def run_jq(filter_file):
    """Run a jq filter against the manifest and return output lines."""
    cmd = ["jq", "-r", "-f", filter_file, "/app/manifest.json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"jq failed:\n{result.stderr}"
    return result.stdout.strip().split("\n") if result.stdout.strip() else []


def run_select(*args):
    """Run orchestrator select and return sorted output lines."""
    cmd = ["python3", "/app/orchestrator.py", "select"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return sorted(lines)


def run_json(subcommand, *args):
    """Run orchestrator subcommand and return parsed JSON."""
    cmd = ["python3", "/app/orchestrator.py", subcommand] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
    return json.loads(result.stdout.strip())


# ─── JQ FILTER TESTS ────────────────────────────────────

class TestJqDepEdges:
    def test_edge_count(self):
        lines = run_jq("/app/jq_filters/dep_edges.jq")
        assert len(lines) == 32

    def test_specific_edges_present(self):
        lines = run_jq("/app/jq_filters/dep_edges.jq")
        edges = {tuple(l.split("\t")) for l in lines}
        assert ("model.analytics.int_customer_orders",
                "model.analytics.stg_customers") in edges
        assert ("model.analytics.mart_revenue",
                "model.analytics.int_regional_sales") in edges
        assert ("exposure.analytics.dashboard_revenue",
                "model.analytics.mart_revenue") in edges

    def test_output_sorted(self):
        lines = run_jq("/app/jq_filters/dep_edges.jq")
        assert lines == sorted(lines)


class TestJqNodeAttrs:
    def test_node_count(self):
        lines = run_jq("/app/jq_filters/node_attrs.jq")
        assert len(lines) == 27

    def test_tag_inheritance_first_parent_only(self):
        """Test node with two parents inherits tags from first parent only.
        relationships_int_customer_orders_cid.s1t2u3 has parents:
        [int_customer_orders (daily), stg_customers (daily,staging)]
        Should get 'daily' from first parent only, not 'daily,staging'."""
        lines = run_jq("/app/jq_filters/node_attrs.jq")
        attrs = {}
        for line in lines:
            parts = line.split("\t")
            attrs[parts[0]] = parts
        uid = "test.analytics.relationships_int_customer_orders_cid.s1t2u3"
        assert uid in attrs
        tags = attrs[uid][4]
        assert tags == "daily", f"Expected 'daily', got '{tags}'"

    def test_tag_inheritance_multi_parent_test(self):
        """relationships_mart_orders should get tags from first parent
        (mart_orders: critical,hourly) only, not from second parent
        (mart_customers: critical,daily)."""
        lines = run_jq("/app/jq_filters/node_attrs.jq")
        attrs = {}
        for line in lines:
            parts = line.split("\t")
            attrs[parts[0]] = parts
        uid = "test.analytics.relationships_mart_orders_customer_id.p7q8r9"
        tags = attrs[uid][4]
        assert tags == "critical,hourly", \
            f"Expected 'critical,hourly', got '{tags}'"


class TestJqFanoutAnalysis:
    def test_line_count(self):
        lines = run_jq("/app/jq_filters/fanout_analysis.jq")
        assert len(lines) == 27

    def test_top_bottleneck(self):
        lines = run_jq("/app/jq_filters/fanout_analysis.jq")
        first = lines[0].split("\t")
        assert first[0] == "model.analytics.mart_customers"
        assert int(first[4]) == 135

    def test_second_bottleneck(self):
        lines = run_jq("/app/jq_filters/fanout_analysis.jq")
        second = lines[1].split("\t")
        assert second[0] == "model.analytics.mart_revenue"
        assert int(second[4]) == 120


# ─── SQLITE TESTS ───────────────────────────────────────

class TestSqliteSchema:
    def test_database_exists(self):
        assert os.path.exists("/app/pipeline.db")

    def test_tables_exist(self):
        conn = sqlite3.connect("/app/pipeline.db")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "nodes" in tables
        assert "edges" in tables
        assert "tags" in tables

    def test_node_count(self):
        conn = sqlite3.connect("/app/pipeline.db")
        count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        conn.close()
        assert count == 27

    def test_edge_count(self):
        conn = sqlite3.connect("/app/pipeline.db")
        count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        conn.close()
        assert count == 32


class TestSqliteViews:
    def test_bottlenecks_view_exists(self):
        conn = sqlite3.connect("/app/pipeline.db")
        views = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall()}
        conn.close()
        assert "v_bottlenecks" in views

    def test_bottlenecks_top_entry(self):
        conn = sqlite3.connect("/app/pipeline.db")
        row = conn.execute(
            "SELECT id, risk_score FROM v_bottlenecks LIMIT 1"
        ).fetchone()
        conn.close()
        assert row[0] == "model.analytics.mart_customers"
        assert row[1] == 135

    def test_test_coverage_untested_count(self):
        conn = sqlite3.connect("/app/pipeline.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM v_test_coverage WHERE test_count = 0"
        ).fetchone()[0]
        conn.close()
        assert count == 9

    def test_test_coverage_most_tested(self):
        conn = sqlite3.connect("/app/pipeline.db")
        row = conn.execute(
            "SELECT id, test_count FROM v_test_coverage "
            "ORDER BY test_count DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row[0] == "model.analytics.stg_customers"
        assert row[1] == 3


# ─── SELECT TESTS ─────────────────────────────────────────

class TestSelectPlainName:
    def test_select_single_model(self):
        result = run_select("--select", "stg_customers")
        assert result == ["model.analytics.stg_customers"]


class TestSelectUnlimitedAncestors:
    def test_plus_prefix_all_ancestors(self):
        result = run_select("--select", "+int_customer_orders")
        expected = sorted([
            "model.analytics.int_customer_orders",
            "model.analytics.stg_customers",
            "model.analytics.stg_orders",
            "source.analytics.raw.customers",
            "source.analytics.raw.orders",
        ])
        assert result == expected


class TestSelectAtOperator:
    def test_at_selects_full_subgraph(self):
        result = run_select("--select", "@int_regional_sales")
        expected = sorted([
            "exposure.analytics.dashboard_revenue",
            "model.analytics.int_customer_orders",
            "model.analytics.int_order_payments",
            "model.analytics.int_regional_sales",
            "model.analytics.mart_customers",
            "model.analytics.mart_revenue",
            "model.analytics.stg_customers",
            "model.analytics.stg_orders",
            "model.analytics.stg_payments",
            "seed.analytics.seed_regions",
            "source.analytics.raw.customers",
            "source.analytics.raw.orders",
            "test.analytics.not_null_mart_revenue_amount.m4n5o6",
        ])
        assert result == expected


class TestSelectTagInheritance:
    def test_tag_critical_with_inherited_tests(self):
        result = run_select("--select", "tag:critical")
        expected = sorted([
            "model.analytics.mart_customers",
            "model.analytics.mart_orders",
            "model.analytics.mart_revenue",
            "test.analytics.not_null_mart_customers_customer_id.g7h8i9",
            "test.analytics.not_null_mart_revenue_amount.m4n5o6",
            "test.analytics.relationships_mart_orders_customer_id.p7q8r9",
            "test.analytics.unique_mart_orders_order_id.j1k2l3",
        ])
        assert result == expected


class TestSelectCommaIntersection:
    def test_ancestors_intersect_tag(self):
        result = run_select("--select", "+mart_customers,tag:critical")
        assert result == ["model.analytics.mart_customers"]


class TestSelectDepthLimited:
    def test_depth_limited_ancestors(self):
        result = run_select("--select", "1+mart_customers")
        expected = sorted([
            "model.analytics.int_customer_orders",
            "model.analytics.int_order_payments",
            "model.analytics.mart_customers",
        ])
        assert result == expected


class TestSelectExclude:
    def test_tag_daily_exclude_staging(self):
        result = run_select("--select", "tag:daily",
                            "--exclude", "tag:staging")
        expected = sorted([
            "model.analytics.int_customer_orders",
            "model.analytics.mart_customers",
            "test.analytics.not_null_mart_customers_customer_id.g7h8i9",
            "test.analytics.relationships_int_customer_orders_cid.s1t2u3",
        ])
        assert result == expected


# ─── SCHEDULE TESTS ───────────────────────────────────────

class TestScheduleAllNoneMax4:
    def test_five_stages(self):
        result = run_json("schedule", "--max-parallel", "4",
                          "--test-behavior", "none")
        assert result["total_stages"] == 5
        assert result["total_duration"] == 154
        stages = result["stages"]
        assert stages[0]["nodes"] == [
            "model.analytics.stg_customers",
            "model.analytics.stg_order_items",
            "model.analytics.stg_orders",
            "model.analytics.stg_payments",
        ]
        assert stages[0]["duration"] == 4
        assert stages[1]["nodes"] == [
            "model.analytics.int_customer_orders",
            "model.analytics.int_order_payments",
            "seed.analytics.seed_categories",
            "seed.analytics.seed_regions",
        ]
        assert stages[1]["duration"] == 20
        assert stages[4]["nodes"] == ["model.analytics.mart_products"]
        assert stages[4]["duration"] == 25


class TestScheduleSubsetBarrier:
    def test_barrier_adds_synthetic_deps(self):
        """With barrier, test blocks downstream models -> 3 stages."""
        result = run_json("schedule",
                          "--select", "stg_orders+1",
                          "--max-parallel", "4",
                          "--test-behavior", "barrier")
        assert result["total_stages"] == 3
        assert result["total_duration"] == 28
        stages = result["stages"]
        assert stages[0]["nodes"] == ["model.analytics.stg_orders"]
        assert stages[1]["nodes"] == [
            "test.analytics.unique_stg_orders_order_id.d4e5f6"
        ]
        assert stages[2]["nodes"] == [
            "model.analytics.int_customer_orders",
            "model.analytics.int_order_payments",
        ]


class TestScheduleSubsetIncluded:
    def test_included_no_barrier(self):
        """Without barrier, tests and models run in parallel -> 2 stages."""
        result = run_json("schedule",
                          "--select", "stg_orders+1",
                          "--max-parallel", "4",
                          "--test-behavior", "included")
        assert result["total_stages"] == 2
        assert result["total_duration"] == 24
        stages = result["stages"]
        assert stages[0]["nodes"] == ["model.analytics.stg_orders"]
        assert stages[1]["nodes"] == [
            "model.analytics.int_customer_orders",
            "model.analytics.int_order_payments",
            "test.analytics.unique_stg_orders_order_id.d4e5f6",
        ]


# ─── CRITICAL PATH TESTS ─────────────────────────────────

class TestCriticalPathAllNone:
    def test_longest_path_through_dag(self):
        result = run_json("critical-path", "--test-behavior", "none")
        assert result["total_duration"] == 97
        assert result["path"] == [
            "model.analytics.stg_orders",
            "model.analytics.int_customer_orders",
            "model.analytics.int_regional_sales",
            "model.analytics.mart_revenue",
        ]


class TestCriticalPathSubset:
    def test_critical_path_with_selection(self):
        result = run_json("critical-path",
                          "--select", "int_order_payments+",
                          "--test-behavior", "none")
        assert result["total_duration"] == 80
        assert result["path"] == [
            "model.analytics.int_order_payments",
            "model.analytics.mart_revenue",
        ]


# ─── IMPACT TEST ──────────────────────────────────────────

class TestImpactAnalysis:
    def test_impact_int_order_payments(self):
        result = run_json("impact",
                          "--node", "model.analytics.int_order_payments")
        expected_affected = sorted([
            "exposure.analytics.dashboard_revenue",
            "model.analytics.mart_customers",
            "model.analytics.mart_orders",
            "model.analytics.mart_revenue",
            "test.analytics.not_null_mart_customers_customer_id.g7h8i9",
            "test.analytics.not_null_mart_revenue_amount.m4n5o6",
            "test.analytics.relationships_mart_orders_customer_id.p7q8r9",
            "test.analytics.unique_mart_orders_order_id.j1k2l3",
        ])
        assert result["affected_nodes"] == expected_affected
        assert result["total_rebuild_cost"] == 153
        expected_tests = sorted([
            "test.analytics.not_null_mart_customers_customer_id.g7h8i9",
            "test.analytics.not_null_mart_revenue_amount.m4n5o6",
            "test.analytics.relationships_mart_orders_customer_id.p7q8r9",
            "test.analytics.unique_mart_orders_order_id.j1k2l3",
        ])
        assert result["affected_tests"] == expected_tests


# ─── DOT FILE TESTS ──────────────────────────────────────

class TestDotFile:
    def test_file_exists(self):
        assert os.path.exists("/app/output/dag.dot")

    def test_valid_digraph(self):
        with open("/app/output/dag.dot") as f:
            content = f.read()
        assert "digraph pipeline" in content

    def test_node_count(self):
        with open("/app/output/dag.dot") as f:
            content = f.read()
        nodes = re.findall(r'"[^"]+"\s*\[.*shape=', content)
        assert len(nodes) == 27

    def test_edge_count(self):
        with open("/app/output/dag.dot") as f:
            content = f.read()
        edges = re.findall(r'"[^"]+"\s*->\s*"[^"]+"', content)
        assert len(edges) == 32

    def test_dot_renders(self):
        """Verify the DOT file can be parsed by graphviz."""
        result = subprocess.run(
            ["dot", "-Tsvg", "/app/output/dag.dot"],
            capture_output=True, timeout=30
        )
        assert result.returncode == 0, \
            f"dot rendering failed:\n{result.stderr.decode()}"
