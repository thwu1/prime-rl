"""
Verification tests for the dagster storage repair/optimization/retention task
and the reconciliation module bug fixes.

Tests run AFTER the agent's scripts (repair_db.py, optimize_db.py, retention.py)
have been executed by test.sh.  The reconciliation module is tested by direct import.

"""

import sqlite3
import sys

DB_PATH = "/app/dagster_storage.db"


# ---------------------------------------------------------------------------
# Repair tests
# ---------------------------------------------------------------------------

class TestRepair:
    """Verify that repair_db.py resolved all integrity violations."""

    def _conn(self):
        return sqlite3.connect(DB_PATH)

    def test_no_orphaned_events(self):
        """Events must not reference run_ids absent from the runs table."""
        conn = self._conn()
        cnt = conn.execute(
            "SELECT COUNT(*) FROM event_logs "
            "WHERE run_id NOT IN (SELECT run_id FROM runs)"
        ).fetchone()[0]
        conn.close()
        assert cnt == 0, "Found {} orphaned events".format(cnt)

    def test_no_zombie_runs(self):
        """No run should remain in STARTED state with no update for >24 h."""
        conn = self._conn()
        max_ts = conn.execute(
            "SELECT MAX(update_timestamp) FROM runs"
        ).fetchone()[0]
        cnt = conn.execute(
            "SELECT COUNT(*) FROM runs "
            "WHERE status = 'STARTED' AND update_timestamp < ?",
            (max_ts - 86400,),
        ).fetchone()[0]
        conn.close()
        assert cnt == 0, "Found {} zombie runs".format(cnt)

    def test_no_duplicate_materializations(self):
        """Each (asset_key, partition_key, run_id) must have at most one
        ASSET_MATERIALIZATION event."""
        conn = self._conn()
        dupes = conn.execute(
            "SELECT asset_key, COALESCE(partition_key, ''), run_id, COUNT(*) AS c "
            "FROM event_logs "
            "WHERE dagster_event_type = 'ASSET_MATERIALIZATION' "
            "GROUP BY asset_key, COALESCE(partition_key, ''), run_id "
            "HAVING c > 1"
        ).fetchall()
        conn.close()
        assert len(dupes) == 0, "Found {} duplicate materialization groups".format(
            len(dupes)
        )

    def test_asset_keys_timestamp_consistent(self):
        """asset_keys.last_materialization_timestamp must match the actual
        latest ASSET_MATERIALIZATION event for that asset."""
        conn = self._conn()
        bad = conn.execute(
            "SELECT ak.asset_key, ak.last_materialization_timestamp, "
            "  (SELECT MAX(e.timestamp) FROM event_logs e "
            "   WHERE e.asset_key = ak.asset_key "
            "   AND e.dagster_event_type = 'ASSET_MATERIALIZATION') AS actual "
            "FROM asset_keys ak "
            "WHERE ak.last_materialization_timestamp IS NOT NULL "
            "AND ABS(ak.last_materialization_timestamp - "
            "  (SELECT MAX(e.timestamp) FROM event_logs e "
            "   WHERE e.asset_key = ak.asset_key "
            "   AND e.dagster_event_type = 'ASSET_MATERIALIZATION')) > 0.01"
        ).fetchall()
        conn.close()
        assert len(bad) == 0, "Inconsistent asset_keys timestamps: {}".format(bad)

    def test_asset_keys_run_id_consistent(self):
        """asset_keys.last_run_id must match the run that produced the
        latest materialization event."""
        conn = self._conn()
        bad = conn.execute(
            "SELECT ak.asset_key, ak.last_run_id, "
            "  (SELECT e.run_id FROM event_logs e "
            "   WHERE e.asset_key = ak.asset_key "
            "   AND e.dagster_event_type = 'ASSET_MATERIALIZATION' "
            "   ORDER BY e.timestamp DESC LIMIT 1) AS actual "
            "FROM asset_keys ak "
            "WHERE ak.last_run_id IS NOT NULL "
            "AND ak.last_run_id != "
            "  (SELECT e.run_id FROM event_logs e "
            "   WHERE e.asset_key = ak.asset_key "
            "   AND e.dagster_event_type = 'ASSET_MATERIALIZATION' "
            "   ORDER BY e.timestamp DESC LIMIT 1)"
        ).fetchall()
        conn.close()
        assert len(bad) == 0, "Inconsistent asset_keys run_ids: {}".format(bad)

    def test_no_orphaned_ticks(self):
        """No job tick should be stuck in STARTED for more than 2 hours."""
        conn = self._conn()
        max_ts = conn.execute(
            "SELECT MAX(timestamp) FROM event_logs"
        ).fetchone()[0]
        cnt = conn.execute(
            "SELECT COUNT(*) FROM job_ticks "
            "WHERE status = 'STARTED' AND timestamp < ?",
            (max_ts - 7200,),
        ).fetchone()[0]
        conn.close()
        assert cnt == 0, "Found {} orphaned ticks".format(cnt)


# ---------------------------------------------------------------------------
# Query optimization tests
# ---------------------------------------------------------------------------

class TestOptimize:
    """Verify that optimize_db.py added indexes eliminating full table scans."""

    def _assert_uses_index(self, query, params):
        conn = sqlite3.connect(DB_PATH)
        plan = conn.execute(
            "EXPLAIN QUERY PLAN " + query, params
        ).fetchall()
        conn.close()
        plan_text = " ".join(str(row) for row in plan)
        ok = ("SEARCH" in plan_text
              or "USING INDEX" in plan_text
              or "USING COVERING INDEX" in plan_text)
        assert ok, "Query not using index.\nQuery: {}\nPlan:  {}".format(
            query, plan_text
        )

    def test_events_by_run(self):
        self._assert_uses_index(
            "SELECT * FROM event_logs WHERE run_id = ? ORDER BY timestamp",
            ("run_0001",),
        )

    def test_latest_materialization(self):
        self._assert_uses_index(
            "SELECT * FROM event_logs "
            "WHERE asset_key = ? "
            "AND dagster_event_type = 'ASSET_MATERIALIZATION' "
            "ORDER BY timestamp DESC LIMIT 1",
            ("raw_events",),
        )

    def test_ticks_by_origin(self):
        self._assert_uses_index(
            "SELECT * FROM job_ticks "
            "WHERE job_origin_id = ? AND timestamp > ? "
            "ORDER BY timestamp DESC",
            ("origin_event_sensor", 1699900000.0),
        )

    def test_events_by_type_timerange(self):
        self._assert_uses_index(
            "SELECT * FROM event_logs "
            "WHERE dagster_event_type = ? AND timestamp BETWEEN ? AND ?",
            ("ASSET_MATERIALIZATION", 1699900000.0, 1700000000.0),
        )

    def test_events_by_asset_partition(self):
        self._assert_uses_index(
            "SELECT * FROM event_logs "
            "WHERE asset_key = ? AND partition_key = ? "
            "ORDER BY timestamp DESC",
            ("raw_events", "2023-11-01"),
        )

    def test_mat_timestamps_by_asset(self):
        self._assert_uses_index(
            "SELECT asset_key, MAX(timestamp) FROM event_logs "
            "WHERE dagster_event_type = 'ASSET_MATERIALIZATION' "
            "GROUP BY asset_key",
            (),
        )

    def test_event_counts_by_timerange(self):
        self._assert_uses_index(
            "SELECT dagster_event_type, COUNT(*) FROM event_logs "
            "WHERE timestamp BETWEEN ? AND ? "
            "GROUP BY dagster_event_type",
            (1699900000.0, 1700000000.0),
        )


# ---------------------------------------------------------------------------
# Retention tests
# ---------------------------------------------------------------------------

class TestRetention:
    """Verify the retention policy pruned old data correctly."""

    def _conn(self):
        return sqlite3.connect(DB_PATH)

    def _cutoff(self, conn):
        max_ts = conn.execute(
            "SELECT MAX(timestamp) FROM event_logs"
        ).fetchone()[0]
        return max_ts - 30 * 86400

    def test_recent_events_preserved(self):
        conn = self._conn()
        cutoff = self._cutoff(conn)
        cnt = conn.execute(
            "SELECT COUNT(*) FROM event_logs WHERE timestamp >= ?", (cutoff,)
        ).fetchone()[0]
        conn.close()
        assert cnt > 0, "All recent events were removed"

    def test_latest_materializations_preserved(self):
        """For every asset that had materializations, at least one must remain."""
        conn = self._conn()
        assets = conn.execute(
            "SELECT asset_key FROM asset_keys "
            "WHERE last_materialization_timestamp IS NOT NULL"
        ).fetchall()
        for (asset_key,) in assets:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM event_logs "
                "WHERE asset_key = ? "
                "AND dagster_event_type = 'ASSET_MATERIALIZATION'",
                (asset_key,),
            ).fetchone()[0]
            assert cnt > 0, (
                "Latest materialization for {} was deleted".format(asset_key)
            )
        conn.close()

    def test_old_non_materialization_events_removed(self):
        """Old non-materialization events from terminal, non-backfill runs
        should all be pruned."""
        conn = self._conn()
        cutoff = self._cutoff(conn)
        cnt = conn.execute(
            "SELECT COUNT(*) FROM event_logs "
            "WHERE timestamp < ? "
            "AND dagster_event_type != 'ASSET_MATERIALIZATION' "
            "AND run_id NOT IN "
            "  (SELECT run_id FROM runs WHERE status IN ('STARTED','NOT_STARTED')) "
            "AND run_id NOT IN "
            "  (SELECT run_id FROM runs WHERE tags_json LIKE '%dagster/backfill%')",
            (cutoff,),
        ).fetchone()[0]
        conn.close()
        assert cnt == 0, "Found {} old non-materialization events".format(cnt)

    def test_old_materializations_only_latest(self):
        """Any old materialization that survived must be either the latest for
        its (asset_key, partition_key) group OR from a backfill run."""
        conn = self._conn()
        cutoff = self._cutoff(conn)
        old_mats = conn.execute(
            "SELECT id, asset_key, COALESCE(partition_key, '') AS pk, "
            "  timestamp, run_id "
            "FROM event_logs "
            "WHERE dagster_event_type = 'ASSET_MATERIALIZATION' "
            "AND timestamp < ?",
            (cutoff,),
        ).fetchall()

        backfill_runs = set(row[0] for row in conn.execute(
            "SELECT run_id FROM runs WHERE tags_json LIKE '%dagster/backfill%'"
        ).fetchall())

        for evt_id, asset_key, pk, ts, run_id in old_mats:
            if run_id in backfill_runs:
                continue
            newer = conn.execute(
                "SELECT COUNT(*) FROM event_logs "
                "WHERE dagster_event_type = 'ASSET_MATERIALIZATION' "
                "AND asset_key = ? AND COALESCE(partition_key, '') = ? "
                "AND timestamp > ?",
                (asset_key, pk, ts),
            ).fetchone()[0]
            assert newer == 0, (
                "Old non-latest non-backfill materialization survived: "
                "id={}, asset={}, partition={}".format(evt_id, asset_key, pk)
            )
        conn.close()

    def test_backfill_run_events_preserved(self):
        """Events from runs tagged as backfill must survive retention."""
        conn = self._conn()
        backfill_run_ids = conn.execute(
            "SELECT run_id FROM runs WHERE tags_json LIKE '%dagster/backfill%'"
        ).fetchall()
        assert len(backfill_run_ids) > 0, "No backfill runs found"
        for (run_id,) in backfill_run_ids:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM event_logs WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            assert cnt > 0, "Events for backfill run {} were deleted".format(run_id)
        conn.close()

    def test_tick_retention_preserves_recent(self):
        """At least 3 ticks per job_origin_id must be preserved."""
        conn = self._conn()
        origins = conn.execute(
            "SELECT DISTINCT job_origin_id FROM job_ticks"
        ).fetchall()
        for (origin,) in origins:
            count = conn.execute(
                "SELECT COUNT(*) FROM job_ticks WHERE job_origin_id = ?",
                (origin,)
            ).fetchone()[0]
            assert count >= 3, (
                "Only {} ticks for {}, expected at least 3".format(count, origin)
            )
        conn.close()

    def test_old_ticks_pruned_beyond_retention(self):
        """Ticks older than cutoff should be pruned unless they are among
        the 3 most recent per job_origin_id."""
        conn = self._conn()
        cutoff = self._cutoff(conn)
        old_non_preserved = conn.execute(
            "SELECT COUNT(*) FROM job_ticks t1 "
            "WHERE t1.timestamp < ? "
            "AND (SELECT COUNT(*) FROM job_ticks t2 "
            "     WHERE t2.job_origin_id = t1.job_origin_id "
            "     AND t2.timestamp > t1.timestamp) >= 3",
            (cutoff,),
        ).fetchone()[0]
        conn.close()
        assert old_non_preserved == 0, (
            "Found {} old ticks beyond top-3 that should have been pruned".format(
                old_non_preserved)
        )


# ---------------------------------------------------------------------------
# Reconciliation module tests
# ---------------------------------------------------------------------------

class TestReconciliation:
    """Verify the fixed reconciliation module passes behavioral tests."""

    @classmethod
    def setup_class(cls):
        if "/app" not in sys.path:
            sys.path.insert(0, "/app")

    # ---- topological_sort ----

    def test_topo_sort_basic(self):
        from pipeline.reconciliation import topological_sort

        result = topological_sort({"A": [], "B": ["A"], "C": ["A", "B"]})
        assert set(result) == {"A", "B", "C"}
        assert result.index("A") < result.index("B")
        assert result.index("B") < result.index("C")

    def test_topo_sort_handles_missing_root_nodes(self):
        """Nodes that appear only as dependencies (not as keys) must still
        appear in the result."""
        from pipeline.reconciliation import topological_sort

        result = topological_sort({"middle": ["root"], "leaf": ["middle"]})
        assert "root" in result, "Root node missing from topological sort"
        assert set(result) == {"root", "middle", "leaf"}
        assert result.index("root") < result.index("middle")
        assert result.index("middle") < result.index("leaf")

    def test_topo_sort_complex_graph(self):
        from pipeline.reconciliation import topological_sort

        deps = {
            "cleaned_events": ["raw_events"],
            "daily_agg": ["cleaned_events"],
            "weekly_reports": ["daily_agg", "daily_users"],
            "daily_users": ["cleaned_users"],
            "cleaned_users": ["raw_users"],
        }
        result = topological_sort(deps)
        assert len(result) == 7, "Expected 7 nodes, got {}".format(len(result))
        assert "raw_events" in result
        assert "raw_users" in result
        assert result.index("raw_events") < result.index("cleaned_events")
        assert result.index("cleaned_users") < result.index("daily_users")
        assert result.index("daily_agg") < result.index("weekly_reports")
        assert result.index("daily_users") < result.index("weekly_reports")

    # ---- get_weekly_partition_for_daily ----

    def test_partition_alignment_monday(self):
        """Monday must map to itself."""
        from pipeline.reconciliation import get_weekly_partition_for_daily

        assert get_weekly_partition_for_daily("2023-11-13") == "2023-11-13"

    def test_partition_alignment_wednesday(self):
        from pipeline.reconciliation import get_weekly_partition_for_daily

        assert get_weekly_partition_for_daily("2023-11-15") == "2023-11-13"

    def test_partition_alignment_sunday(self):
        from pipeline.reconciliation import get_weekly_partition_for_daily

        assert get_weekly_partition_for_daily("2023-11-19") == "2023-11-13"

    def test_partition_alignment_saturday(self):
        from pipeline.reconciliation import get_weekly_partition_for_daily

        assert get_weekly_partition_for_daily("2023-11-18") == "2023-11-13"

    # ---- find_stale_assets ----

    def test_staleness_any_upstream_newer(self):
        """Asset is stale if ANY upstream is newer (not only when ALL are)."""
        from pipeline.reconciliation import find_stale_assets

        deps = {"root1": [], "root2": [], "downstream": ["root1", "root2"]}
        times = {"root1": 100.0, "root2": 300.0, "downstream": 200.0}
        stale = find_stale_assets(deps, times)
        assert "downstream" in stale, (
            "downstream should be stale because root2 (t=300) > downstream (t=200)"
        )

    def test_staleness_all_older(self):
        from pipeline.reconciliation import find_stale_assets

        deps = {"root1": [], "root2": [], "downstream": ["root1", "root2"]}
        times = {"root1": 100.0, "root2": 150.0, "downstream": 200.0}
        stale = find_stale_assets(deps, times)
        assert "downstream" not in stale

    def test_staleness_never_materialized(self):
        from pipeline.reconciliation import find_stale_assets

        deps = {"root": [], "child": ["root"]}
        times = {"root": 100.0}
        stale = find_stale_assets(deps, times)
        assert "child" in stale

    def test_staleness_single_upstream_newer(self):
        from pipeline.reconciliation import find_stale_assets

        deps = {"A": [], "B": [], "C": [], "D": ["A", "B", "C"]}
        times = {"A": 50.0, "B": 60.0, "C": 300.0, "D": 200.0}
        stale = find_stale_assets(deps, times)
        assert "D" in stale, "D should be stale because C (t=300) > D (t=200)"

    # ---- compute_reconciliation_plan (transitive staleness) ----

    def test_transitive_staleness_propagation(self):
        """If A->B->C and A is rematerialized after B and C, both B and C
        should appear in the reconciliation plan (transitive staleness)."""
        from pipeline.reconciliation import compute_reconciliation_plan

        deps = {"A": [], "B": ["A"], "C": ["B"]}
        times = {"A": 300.0, "B": 200.0, "C": 250.0}
        plan = compute_reconciliation_plan(deps, times)
        assert "B" in plan, "B should be in plan (direct staleness: A > B)"
        assert "C" in plan, "C should be in plan (transitive: B is stale)"

    def test_transitive_staleness_multi_upstream(self):
        """Transitive staleness through a multi-upstream graph."""
        from pipeline.reconciliation import compute_reconciliation_plan

        deps = {"X": [], "Y": [], "Z": ["X", "Y"], "W": ["Z"]}
        times = {"X": 300.0, "Y": 50.0, "Z": 200.0, "W": 250.0}
        plan = compute_reconciliation_plan(deps, times)
        assert "Z" in plan, "Z should be stale (X is newer)"
        assert "W" in plan, "W should be stale (transitive from Z)"
        assert "X" not in plan, "X has no deps, not stale"
        assert "Y" not in plan, "Y has no deps, not stale"

    # ---- validate_partition_completeness ----

    def test_partition_completeness_full_week(self):
        from pipeline.reconciliation import validate_partition_completeness

        partitions = {"2023-11-13", "2023-11-14", "2023-11-15", "2023-11-16",
                      "2023-11-17", "2023-11-18", "2023-11-19"}
        assert validate_partition_completeness("2023-11-13", partitions) is True

    def test_partition_completeness_missing_sunday(self):
        """Sunday must be included in the 7-day check window."""
        from pipeline.reconciliation import validate_partition_completeness

        partitions = {"2023-11-13", "2023-11-14", "2023-11-15", "2023-11-16",
                      "2023-11-17", "2023-11-18"}
        assert validate_partition_completeness("2023-11-13", partitions) is False

    def test_partition_completeness_missing_middle(self):
        from pipeline.reconciliation import validate_partition_completeness

        partitions = {"2023-11-13", "2023-11-14", "2023-11-16",
                      "2023-11-17", "2023-11-18", "2023-11-19"}
        assert validate_partition_completeness("2023-11-13", partitions) is False
