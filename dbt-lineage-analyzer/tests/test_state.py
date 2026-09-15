"""
Verification tests for dbt pipeline forensics report.

"""
import json
import os
import re
import sqlite3

import pytest


@pytest.fixture(scope="session")
def forensics():
    with open("/app/forensics.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def manifest():
    with open("/data/manifest.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def run_results():
    """Load all run results from SQLite."""
    conn = sqlite3.connect("/data/pipeline_runs.db")
    c = conn.cursor()
    runs = [r[0] for r in c.execute(
        "SELECT run_id FROM runs ORDER BY run_id").fetchall()]
    results = {}
    for run_id in runs:
        rows = c.execute(
            "SELECT unique_id, status FROM node_results WHERE run_id=?",
            (run_id,)).fetchall()
        results[run_id] = {uid: st for uid, st in rows}
    conn.close()
    return results


# -----------------------------------------------------------------------
# Graph Drift
# -----------------------------------------------------------------------
class TestDrift:
    def test_added_models(self, forensics):
        expected = [
            "fct_regional_sales",
            "int_order_enriched",
            "int_regional_orders",
            "rpt_regional_performance",
            "stg_regions",
        ]
        assert forensics["drift"]["added"] == expected

    def test_removed_models(self, forensics):
        expected = ["int_legacy_orders"]
        assert forensics["drift"]["removed"] == expected

    def test_dependency_changes_keys(self, forensics):
        dc = forensics["drift"]["dependency_changes"]
        assert list(dc.keys()) == ["fct_orders"]

    def test_fct_orders_added_dep(self, forensics):
        dc = forensics["drift"]["dependency_changes"]
        assert dc["fct_orders"] == ["int_order_enriched"]

    def test_line_comment_trap(self, forensics):
        """fct_payments has ref('int_legacy_orders') inside a SQL line comment.
        If parsed incorrectly, int_legacy_orders would NOT appear in removed."""
        assert "int_legacy_orders" in forensics["drift"]["removed"]

    def test_jinja_block_comment_trap(self, forensics):
        """fct_inventory_snapshots has ref('stg_warehouses') inside {# ... #}.
        If parsed incorrectly, stg_warehouses appears as a dependency change."""
        dc = forensics["drift"]["dependency_changes"]
        assert "fct_inventory_snapshots" not in dc

    def test_sql_block_comment_trap(self, forensics):
        """int_supplier_products has ref('int_legacy_orders') inside /* ... */.
        If parsed incorrectly, int_legacy_orders appears as a dependency change."""
        dc = forensics["drift"]["dependency_changes"]
        assert "int_supplier_products" not in dc

    def test_added_sorted(self, forensics):
        added = forensics["drift"]["added"]
        assert added == sorted(added)

    def test_removed_sorted(self, forensics):
        removed = forensics["drift"]["removed"]
        assert removed == sorted(removed)

    def test_no_extra_dependency_changes(self, forensics):
        """Only fct_orders should have dependency changes."""
        dc = forensics["drift"]["dependency_changes"]
        assert len(dc) == 1


# -----------------------------------------------------------------------
# Root Causes by Run
# -----------------------------------------------------------------------
class TestRootCausesByRun:
    def test_run_001(self, forensics):
        expected = [
            "model.analytics.fct_orders",
            "model.analytics.int_product_inventory",
        ]
        assert forensics["root_causes_by_run"]["run_001"] == expected

    def test_run_002(self, forensics):
        expected = [
            "model.analytics.int_product_inventory",
            "model.analytics.stg_payments",
        ]
        assert forensics["root_causes_by_run"]["run_002"] == expected

    def test_run_003(self, forensics):
        expected = ["model.analytics.fct_orders"]
        assert forensics["root_causes_by_run"]["run_003"] == expected

    def test_all_runs_present(self, forensics):
        assert sorted(forensics["root_causes_by_run"].keys()) == [
            "run_001", "run_002", "run_003"
        ]

    def test_root_causes_sorted(self, forensics):
        for run_id, rcs in forensics["root_causes_by_run"].items():
            assert rcs == sorted(rcs), f"root causes in {run_id} not sorted"

    def test_root_causes_exist_in_manifest(self, forensics, manifest):
        for run_id, rcs in forensics["root_causes_by_run"].items():
            for uid in rcs:
                assert uid in manifest["nodes"], (
                    f"root cause {uid} in {run_id} not in manifest"
                )

    def test_root_causes_actually_failed(self, forensics, run_results):
        for run_id, rcs in forensics["root_causes_by_run"].items():
            for uid in rcs:
                assert run_results[run_id][uid] in ("error", "skipped"), (
                    f"{uid} in {run_id} has status "
                    f"{run_results[run_id].get(uid)}, expected error/skipped"
                )

    def test_root_causes_no_failed_upstream(self, forensics, manifest,
                                            run_results):
        for run_id, rcs in forensics["root_causes_by_run"].items():
            status_map = run_results[run_id]
            for uid in rcs:
                for dep in manifest["nodes"][uid]["depends_on"]["nodes"]:
                    dep_st = status_map.get(dep, "pass")
                    assert dep_st == "pass", (
                        f"root cause {uid} in {run_id} has failed "
                        f"upstream {dep} ({dep_st})"
                    )

    def test_fct_orders_masked_in_run_002(self, forensics, run_results):
        """fct_orders fails in run_002 but is NOT a root cause (masked)."""
        assert run_results["run_002"]["model.analytics.fct_orders"] == "error"
        assert "model.analytics.fct_orders" not in (
            forensics["root_causes_by_run"]["run_002"]
        )


# -----------------------------------------------------------------------
# Persistent vs Transient Root Causes
# -----------------------------------------------------------------------
class TestFailureClassification:
    def test_persistent_root_cause(self, forensics):
        assert forensics["persistent_root_cause"] == [
            "model.analytics.fct_orders"
        ]

    def test_transient_root_causes(self, forensics):
        assert forensics["transient_root_causes"] == [
            "model.analytics.int_product_inventory",
            "model.analytics.stg_payments",
        ]

    def test_persistent_fails_in_all_runs(self, forensics, run_results):
        for uid in forensics["persistent_root_cause"]:
            for run_id, status_map in run_results.items():
                assert status_map.get(uid, "pass") in ("error", "skipped"), (
                    f"persistent root cause {uid} has status "
                    f"{status_map.get(uid)} in {run_id}"
                )

    def test_transient_passes_in_some_run(self, forensics, run_results):
        for uid in forensics["transient_root_causes"]:
            has_pass = any(
                sm.get(uid, "pass") == "pass"
                for sm in run_results.values()
            )
            assert has_pass, (
                f"transient root cause {uid} never passes in any run"
            )

    def test_persistent_sorted(self, forensics):
        p = forensics["persistent_root_cause"]
        assert p == sorted(p)

    def test_transient_sorted(self, forensics):
        t = forensics["transient_root_causes"]
        assert t == sorted(t)

    def test_no_overlap(self, forensics):
        p = set(forensics["persistent_root_cause"])
        t = set(forensics["transient_root_causes"])
        assert p.isdisjoint(t), (
            f"overlap between persistent and transient: {p & t}"
        )


# -----------------------------------------------------------------------
# Masked Failures
# -----------------------------------------------------------------------
class TestMaskedFailures:
    def test_masked_keys(self, forensics):
        assert sorted(forensics["masked_in_runs"].keys()) == [
            "model.analytics.fct_orders"
        ]

    def test_fct_orders_masked_run_002(self, forensics):
        assert forensics["masked_in_runs"]["model.analytics.fct_orders"] == [
            "run_002"
        ]

    def test_masked_runs_sorted(self, forensics):
        for uid, runs in forensics["masked_in_runs"].items():
            assert runs == sorted(runs)

    def test_masked_node_actually_failed(self, forensics, run_results):
        for uid, runs in forensics["masked_in_runs"].items():
            for run_id in runs:
                assert run_results[run_id][uid] in ("error", "skipped"), (
                    f"masked node {uid} has status "
                    f"{run_results[run_id].get(uid)} in {run_id}"
                )

    def test_masked_node_not_root_cause_in_masked_run(self, forensics):
        for uid, runs in forensics["masked_in_runs"].items():
            for run_id in runs:
                assert uid not in forensics["root_causes_by_run"][run_id]


# -----------------------------------------------------------------------
# Stale Selectors
# -----------------------------------------------------------------------
class TestStaleSelectors:
    def test_stale_selectors(self, forensics):
        assert forensics["stale_selectors"] == [
            "orders_pipeline",
            "supplier_analysis",
        ]

    def test_stale_selectors_sorted(self, forensics):
        ss = forensics["stale_selectors"]
        assert ss == sorted(ss)

    def test_stale_selectors_reference_missing_models(self, forensics):
        """Verify that stale selector model names don't exist as source files."""
        model_dir = "/data/models"
        source_names = set()
        for root, dirs, files in os.walk(model_dir):
            for f in files:
                if f.endswith(".sql"):
                    source_names.add(f[:-4])
        assert "int_legacy_orders" not in source_names
        assert "rpt_supplier_performance" not in source_names


# -----------------------------------------------------------------------
# Blocking Dependency
# -----------------------------------------------------------------------
class TestBlockingDependency:
    def test_blocking_dependency(self, forensics):
        assert forensics["blocking_dependency"] == "int_order_enriched"

    def test_blocking_dep_in_source_sql(self, forensics):
        """The blocking dep should appear as a ref() in fct_orders source."""
        with open("/data/models/marts/fct_orders.sql") as f:
            sql = f.read()
        bd = forensics["blocking_dependency"]
        assert re.search(
            r"\{\{\s*ref\(\s*['\"]" + re.escape(bd) + r"['\"]\s*\)\s*\}\}",
            sql
        ), f"blocking dep {bd} not found in fct_orders source SQL"

    def test_blocking_dep_not_in_manifest(self, forensics, manifest):
        """The blocking dep should NOT exist as a model node in manifest."""
        bd = forensics["blocking_dependency"]
        uid = f"model.analytics.{bd}"
        assert uid not in manifest["nodes"], (
            f"blocking dep {bd} should not be in manifest"
        )

    def test_blocking_dep_is_added_model(self, forensics):
        """The blocking dep should be one of the drift-added models."""
        assert forensics["blocking_dependency"] in forensics["drift"]["added"]


# -----------------------------------------------------------------------
# Cascade Impact
# -----------------------------------------------------------------------
class TestCascadeImpact:
    def test_cascade_impact_keys(self, forensics):
        """All root causes from any run should have a cascade_impact entry."""
        all_rcs = set()
        for rcs in forensics["root_causes_by_run"].values():
            all_rcs.update(rcs)
        assert set(forensics["cascade_impact"].keys()) == all_rcs

    def test_fct_orders_cascade(self, forensics):
        """fct_orders has 2 downstream models: rpt_daily_revenue,
        rpt_customer_lifetime_value."""
        assert forensics["cascade_impact"]["model.analytics.fct_orders"] == 2

    def test_int_product_inventory_cascade(self, forensics):
        """int_product_inventory has 2 downstream models:
        fct_inventory_snapshots, rpt_product_performance."""
        ci = forensics["cascade_impact"]
        assert ci["model.analytics.int_product_inventory"] == 2

    def test_stg_payments_cascade(self, forensics):
        """stg_payments has 5 downstream models: int_payment_methods,
        fct_orders, fct_payments, rpt_daily_revenue,
        rpt_customer_lifetime_value."""
        assert forensics["cascade_impact"]["model.analytics.stg_payments"] == 5

    def test_cascade_counts_models_only(self, forensics, manifest):
        """Cascade impact should count only model nodes, not tests or seeds."""
        for uid, count in forensics["cascade_impact"].items():
            # Verify by computing transitive downstream model count
            visited = set()
            queue = [uid]
            while queue:
                node_id = queue.pop(0)
                for child_id in manifest.get("child_map", {}).get(node_id, []):
                    if child_id not in visited:
                        visited.add(child_id)
                        queue.append(child_id)
            model_count = sum(
                1 for v in visited
                if manifest["nodes"].get(v, {}).get("resource_type") == "model"
            )
            assert count == model_count, (
                f"{uid}: expected {model_count} downstream models, got {count}"
            )


# -----------------------------------------------------------------------
# Fix Priority
# -----------------------------------------------------------------------
class TestFixPriority:
    def test_fix_priority_order(self, forensics):
        """stg_payments(1*5=5) > fct_orders(2*2=4) >
        int_product_inventory(2*2=4), alpha tiebreak."""
        expected = [
            "model.analytics.stg_payments",
            "model.analytics.fct_orders",
            "model.analytics.int_product_inventory",
        ]
        assert forensics["fix_priority"] == expected

    def test_fix_priority_contains_all_root_causes(self, forensics):
        all_rcs = set()
        for rcs in forensics["root_causes_by_run"].values():
            all_rcs.update(rcs)
        assert set(forensics["fix_priority"]) == all_rcs

    def test_fix_priority_scores_descending(self, forensics):
        """Verify scores are non-increasing."""
        rc_by_run = forensics["root_causes_by_run"]
        ci = forensics["cascade_impact"]
        scores = []
        for uid in forensics["fix_priority"]:
            runs_as_rc = sum(
                1 for rcs in rc_by_run.values() if uid in rcs
            )
            score = runs_as_rc * ci[uid]
            scores.append(score)
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"fix_priority not sorted by score: {scores}"
            )


# -----------------------------------------------------------------------
# Structural Integrity
# -----------------------------------------------------------------------
class TestStructuralIntegrity:
    def test_forensics_has_all_keys(self, forensics):
        required = {
            "drift", "root_causes_by_run", "persistent_root_cause",
            "transient_root_causes", "masked_in_runs",
            "stale_selectors", "blocking_dependency",
            "cascade_impact", "fix_priority",
        }
        assert required.issubset(set(forensics.keys()))

    def test_drift_has_all_keys(self, forensics):
        required = {"added", "removed", "dependency_changes"}
        assert required.issubset(set(forensics["drift"].keys()))
