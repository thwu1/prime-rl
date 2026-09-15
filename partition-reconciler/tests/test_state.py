"""Tests for the partition reconciliation system.

"""

import pytest
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/app")

from partitions import (
    DailyPartitionDef,
    HourlyPartitionDef,
    StaticPartitionDef,
    MultiPartitionDef,
    MultiPartitionKey,
)
from mappings import IdentityMapping, HourlyToDailyMapping, MultiToDailyMapping
from reconciler import AssetNode, AssetGraph, MaterializationState, Reconciler
from io_manager import PartitionedIOManager
from db_store import SqliteMaterializationStore
from config_loader import load_pipeline


# ---------------------------------------------------------------------------
# Partition definition tests
# ---------------------------------------------------------------------------

class TestPartitionDefs:
    def test_daily_keys(self):
        d = DailyPartitionDef("2024-01-01", "2024-01-03")
        assert d.get_keys() == ["2024-01-01", "2024-01-02", "2024-01-03"]

    def test_multi_partition_keys(self):
        m = MultiPartitionDef({
            "day": DailyPartitionDef("2024-01-01", "2024-01-02"),
            "metric": StaticPartitionDef(["temp", "humidity"]),
        })
        keys = m.get_keys()
        assert len(keys) == 4
        assert "day=2024-01-01|metric=temp" in keys
        assert "day=2024-01-02|metric=humidity" in keys

    def test_multi_partition_key_roundtrip(self):
        mpk = MultiPartitionKey({"day": "2024-01-01", "source": "A", "metric": "x"})
        s = str(mpk)
        parsed = MultiPartitionKey.from_str(s)
        assert parsed == mpk


# ---------------------------------------------------------------------------
# Partition mapping tests
# ---------------------------------------------------------------------------

class TestPartitionMappings:
    def test_multi_to_daily_downstream(self):
        multi = MultiPartitionDef({
            "day": DailyPartitionDef("2024-01-01", "2024-01-02"),
            "metric": StaticPartitionDef(["temp", "humidity"]),
        })
        daily = DailyPartitionDef("2024-01-01", "2024-01-02")
        mapping = MultiToDailyMapping(multi, daily)

        result = mapping.get_downstream_keys("day=2024-01-01|metric=temp")
        assert result == ["2024-01-01"]

    def test_multi_to_daily_upstream_single_nontimed(self):
        """With one non-time dimension, upstream keys should enumerate all values."""
        multi = MultiPartitionDef({
            "day": DailyPartitionDef("2024-01-01", "2024-01-01"),
            "metric": StaticPartitionDef(["temp", "humidity"]),
        })
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        mapping = MultiToDailyMapping(multi, daily)

        upstream = mapping.get_upstream_keys("2024-01-01")
        assert len(upstream) == 2
        assert "day=2024-01-01|metric=temp" in upstream
        assert "day=2024-01-01|metric=humidity" in upstream

    def test_multi_to_daily_upstream_multi_nontimed(self):
        """With multiple non-time dimensions, upstream keys must be the full
        Cartesian product of all non-time dimensions for the given day."""
        multi = MultiPartitionDef({
            "day": DailyPartitionDef("2024-01-01", "2024-01-01"),
            "source": StaticPartitionDef(["A", "B"]),
            "metric": StaticPartitionDef(["x", "y"]),
        })
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        mapping = MultiToDailyMapping(multi, daily)

        upstream = mapping.get_upstream_keys("2024-01-01")
        assert len(upstream) == 4, (
            f"Expected 4 upstream keys (2 sources x 2 metrics), got {len(upstream)}: {upstream}"
        )

        for key_str in upstream:
            mpk = MultiPartitionKey.from_str(key_str)
            assert set(mpk.keys_by_dimension.keys()) == {"day", "source", "metric"}, (
                f"Key {key_str} is missing dimensions; has {set(mpk.keys_by_dimension.keys())}"
            )
            assert mpk.keys_by_dimension["day"] == "2024-01-01"

        expected = {
            "day=2024-01-01|metric=x|source=A",
            "day=2024-01-01|metric=x|source=B",
            "day=2024-01-01|metric=y|source=A",
            "day=2024-01-01|metric=y|source=B",
        }
        assert set(upstream) == expected


# ---------------------------------------------------------------------------
# IO manager tests
# ---------------------------------------------------------------------------

class TestIOManager:
    def test_roundtrip_simple_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PartitionedIOManager(tmpdir)
            data = {"value": 42}
            mgr.write("my_asset", "2024-01-01", data, "run-001")
            result = mgr.read("my_asset", "2024-01-01")
            assert result == data

    def test_roundtrip_multi_partition_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PartitionedIOManager(tmpdir)
            data = {"temperature": 72.5, "readings": [1, 2, 3]}
            pk = "day=2024-01-01|metric=temperature"
            mgr.write("sensor_data", pk, data, "run-001")
            result = mgr.read("sensor_data", pk)
            assert result == data, (
                f"Data mismatch after write/read with multi-partition key '{pk}'"
            )

    def test_read_multiple(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PartitionedIOManager(tmpdir)
            mgr.write("asset", "p1", {"v": 1}, "r1")
            mgr.write("asset", "p2", {"v": 2}, "r1")
            results = mgr.read_multiple("asset", ["p1", "p2"])
            assert results == [{"v": 1}, {"v": 2}]


# ---------------------------------------------------------------------------
# Topological sort tests
# ---------------------------------------------------------------------------

class TestTopoSort:
    def test_chain(self):
        """A -> B -> C must produce [A, B, C]."""
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        graph = AssetGraph()
        # Deliberately add in reverse order to exercise the sort
        graph.add_node(AssetNode("C", daily, {"B": IdentityMapping()}))
        graph.add_node(AssetNode("B", daily, {"A": IdentityMapping()}))
        graph.add_node(AssetNode("A", daily, {}))

        order = graph.topo_sort()
        assert order.index("A") < order.index("B"), f"A must precede B, got {order}"
        assert order.index("B") < order.index("C"), f"B must precede C, got {order}"

    def test_diamond(self):
        """Diamond: A -> {B, C} -> D."""
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        graph = AssetGraph()
        graph.add_node(AssetNode("D", daily, {"B": IdentityMapping(), "C": IdentityMapping()}))
        graph.add_node(AssetNode("B", daily, {"A": IdentityMapping()}))
        graph.add_node(AssetNode("C", daily, {"A": IdentityMapping()}))
        graph.add_node(AssetNode("A", daily, {}))

        order = graph.topo_sort()
        assert order.index("A") < order.index("B"), f"A must precede B, got {order}"
        assert order.index("A") < order.index("C"), f"A must precede C, got {order}"
        assert order.index("B") < order.index("D"), f"B must precede D, got {order}"
        assert order.index("C") < order.index("D"), f"C must precede D, got {order}"


# ---------------------------------------------------------------------------
# Staleness detection tests - "any" mode (default)
# ---------------------------------------------------------------------------

class TestStalenessAnyMode:
    def test_fresh_partition(self):
        """Downstream materialized after upstream should NOT be stale."""
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        graph = AssetGraph()
        graph.add_node(AssetNode("upstream", daily, {}))
        graph.add_node(AssetNode("downstream", daily, {"upstream": IdentityMapping()}))

        state = MaterializationState()
        state.mark_materialized("upstream", "2024-01-01", "r1", 100.0)
        state.mark_materialized("downstream", "2024-01-01", "r2", 200.0)

        result = Reconciler(graph, state).reconcile()
        assert "2024-01-01" not in result.get_stale("downstream"), (
            "Downstream materialized AFTER upstream should be fresh"
        )

    def test_upstream_rematerialized(self):
        """Re-materializing upstream should make downstream stale."""
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        graph = AssetGraph()
        graph.add_node(AssetNode("upstream", daily, {}))
        graph.add_node(AssetNode("downstream", daily, {"upstream": IdentityMapping()}))

        state = MaterializationState()
        state.mark_materialized("upstream", "2024-01-01", "r1", 100.0)
        state.mark_materialized("downstream", "2024-01-01", "r2", 200.0)
        state.mark_materialized("upstream", "2024-01-01", "r3", 300.0)

        result = Reconciler(graph, state).reconcile()
        assert "2024-01-01" in result.get_stale("downstream"), (
            "Downstream should be stale after upstream is re-materialized"
        )

    def test_transitive_staleness(self):
        """Staleness must propagate: A -> B -> C.
        Re-materializing A should make both B and C stale."""
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        graph = AssetGraph()
        graph.add_node(AssetNode("C", daily, {"B": IdentityMapping()}))
        graph.add_node(AssetNode("B", daily, {"A": IdentityMapping()}))
        graph.add_node(AssetNode("A", daily, {}))

        state = MaterializationState()
        state.mark_materialized("A", "2024-01-01", "r1", 100.0)
        state.mark_materialized("B", "2024-01-01", "r2", 200.0)
        state.mark_materialized("C", "2024-01-01", "r3", 300.0)
        state.mark_materialized("A", "2024-01-01", "r4", 400.0)

        result = Reconciler(graph, state).reconcile()
        assert "2024-01-01" in result.get_stale("B"), (
            "B should be stale (direct upstream A was re-materialized)"
        )
        assert "2024-01-01" in result.get_stale("C"), (
            "C should be transitively stale (B is stale, so C is stale too)"
        )


# ---------------------------------------------------------------------------
# Staleness detection tests - "all" mode
# ---------------------------------------------------------------------------

class TestStalenessAllMode:
    def test_not_stale_when_some_upstream_newer(self):
        """In 'all' mode, NOT stale if only some upstreams are newer."""
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        graph = AssetGraph()

        graph.add_node(AssetNode("src_a", daily, {}))
        graph.add_node(AssetNode("src_b", daily, {}))
        graph.add_node(AssetNode("combined", daily, {
            "src_a": IdentityMapping(),
            "src_b": IdentityMapping()
        }, staleness_mode="all"))

        state = MaterializationState()
        state.mark_materialized("src_a", "2024-01-01", "r1", 100.0)
        state.mark_materialized("src_b", "2024-01-01", "r1", 100.0)
        state.mark_materialized("combined", "2024-01-01", "r2", 200.0)

        # Re-materialize ONLY src_a
        state.mark_materialized("src_a", "2024-01-01", "r3", 300.0)

        result = Reconciler(graph, state).reconcile()
        assert "2024-01-01" not in result.get_stale("combined"), (
            "In 'all' mode, should not be stale when only some upstreams are newer"
        )

    def test_stale_when_all_upstream_newer(self):
        """In 'all' mode, IS stale when ALL upstreams are newer."""
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        graph = AssetGraph()

        graph.add_node(AssetNode("src_a", daily, {}))
        graph.add_node(AssetNode("src_b", daily, {}))
        graph.add_node(AssetNode("combined", daily, {
            "src_a": IdentityMapping(),
            "src_b": IdentityMapping()
        }, staleness_mode="all"))

        state = MaterializationState()
        state.mark_materialized("src_a", "2024-01-01", "r1", 100.0)
        state.mark_materialized("src_b", "2024-01-01", "r1", 100.0)
        state.mark_materialized("combined", "2024-01-01", "r2", 200.0)

        # Re-materialize BOTH
        state.mark_materialized("src_a", "2024-01-01", "r3", 300.0)
        state.mark_materialized("src_b", "2024-01-01", "r3", 300.0)

        result = Reconciler(graph, state).reconcile()
        assert "2024-01-01" in result.get_stale("combined"), (
            "In 'all' mode, should be stale when ALL upstreams are newer"
        )

    def test_all_mode_with_transitive_downstream(self):
        """When an 'all'-mode asset becomes stale, downstream 'any'-mode
        assets should also become stale via transitive propagation."""
        daily = DailyPartitionDef("2024-01-01", "2024-01-01")
        graph = AssetGraph()

        graph.add_node(AssetNode("src_a", daily, {}))
        graph.add_node(AssetNode("src_b", daily, {}))
        graph.add_node(AssetNode("combined", daily, {
            "src_a": IdentityMapping(),
            "src_b": IdentityMapping()
        }, staleness_mode="all"))
        graph.add_node(AssetNode("final", daily, {
            "combined": IdentityMapping()
        }))  # default "any" mode

        state = MaterializationState()
        state.mark_materialized("src_a", "2024-01-01", "r1", 100.0)
        state.mark_materialized("src_b", "2024-01-01", "r1", 100.0)
        state.mark_materialized("combined", "2024-01-01", "r2", 200.0)
        state.mark_materialized("final", "2024-01-01", "r3", 300.0)

        # Re-materialize both sources
        state.mark_materialized("src_a", "2024-01-01", "r4", 400.0)
        state.mark_materialized("src_b", "2024-01-01", "r4", 400.0)

        result = Reconciler(graph, state).reconcile()
        assert "2024-01-01" in result.get_stale("combined"), (
            "combined should be stale (all mode, both sources newer)"
        )
        assert "2024-01-01" in result.get_stale("final"), (
            "final should be transitively stale (upstream combined is stale)"
        )


# ---------------------------------------------------------------------------
# Database store tests
# ---------------------------------------------------------------------------

class TestDatabaseStore:
    def _make_db(self):
        """Create a temporary database with the materializations schema."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_path = tmp.name
        tmp.close()
        conn = sqlite3.connect(tmp_path)
        conn.execute(
            "CREATE TABLE materializations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "asset_key TEXT, partition_key TEXT, "
            "run_id TEXT, timestamp REAL)"
        )
        return tmp_path, conn

    def test_basic_store_operations(self):
        """Basic insert and query should work."""
        tmp_path, conn = self._make_db()
        try:
            conn.execute(
                "INSERT INTO materializations "
                "(asset_key, partition_key, run_id, timestamp) "
                "VALUES (?, ?, ?, ?)",
                ("asset1", "p1", "run-1", 100.0)
            )
            conn.commit()
            conn.close()

            store = SqliteMaterializationStore(tmp_path)
            assert store.is_materialized("asset1", "p1")
            assert not store.is_materialized("asset1", "p2")

            record = store.get_record("asset1", "p1")
            assert record is not None
            assert record.run_id == "run-1"
            assert record.timestamp == 100.0
            store.close()
        finally:
            os.unlink(tmp_path)

    def test_returns_latest_for_duplicates(self):
        """When multiple records exist, should return the latest timestamp."""
        tmp_path, conn = self._make_db()
        try:
            conn.execute(
                "INSERT INTO materializations "
                "(asset_key, partition_key, run_id, timestamp) "
                "VALUES (?, ?, ?, ?)",
                ("asset1", "p1", "run-old", 100.0)
            )
            conn.execute(
                "INSERT INTO materializations "
                "(asset_key, partition_key, run_id, timestamp) "
                "VALUES (?, ?, ?, ?)",
                ("asset1", "p1", "run-new", 200.0)
            )
            conn.commit()
            conn.close()

            store = SqliteMaterializationStore(tmp_path)
            record = store.get_record("asset1", "p1")
            assert record.timestamp == 200.0, (
                f"Expected latest timestamp 200.0, got {record.timestamp}"
            )
            assert record.run_id == "run-new", (
                f"Expected latest run_id 'run-new', got '{record.run_id}'"
            )
            store.close()
        finally:
            os.unlink(tmp_path)

    def test_normalizes_millisecond_timestamps(self):
        """Timestamps in milliseconds should be normalized to seconds."""
        tmp_path, conn = self._make_db()
        try:
            conn.execute(
                "INSERT INTO materializations "
                "(asset_key, partition_key, run_id, timestamp) "
                "VALUES (?, ?, ?, ?)",
                ("asset1", "p1", "run-1", 1704067200000.0)
            )
            conn.commit()
            conn.close()

            store = SqliteMaterializationStore(tmp_path)
            record = store.get_record("asset1", "p1")
            assert record.timestamp < 1e12, (
                f"Timestamp should be normalized from milliseconds, got {record.timestamp}"
            )
            assert abs(record.timestamp - 1704067200.0) < 0.001, (
                f"Expected ~1704067200.0, got {record.timestamp}"
            )
            store.close()
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Config loader tests
# ---------------------------------------------------------------------------

class TestConfigLoader:
    def test_loads_staleness_mode(self):
        """Config loader should set staleness_mode on AssetNode objects."""
        graph = load_pipeline("/app/pipeline.yaml")
        assert graph.nodes["summary"].staleness_mode == "all", (
            "summary should have staleness_mode='all'"
        )
        assert graph.nodes["report"].staleness_mode == "any", (
            "report should have staleness_mode='any' (default)"
        )

    def test_correct_multi_to_daily_mapping(self):
        """Config-loaded multi-to-daily mapping should produce correct
        upstream keys with the right time dimension and Cartesian product."""
        graph = load_pipeline("/app/pipeline.yaml")
        summary_node = graph.nodes["summary"]
        mapping = summary_node.deps["raw"]

        upstream_keys = mapping.get_upstream_keys("2024-01-01")
        assert len(upstream_keys) == 4, (
            f"Expected 4 upstream keys (2 sources x 2 metrics), "
            f"got {len(upstream_keys)}: {upstream_keys}"
        )

        for key_str in upstream_keys:
            mpk = MultiPartitionKey.from_str(key_str)
            assert set(mpk.keys_by_dimension.keys()) == {"day", "source", "metric"}, (
                f"Key {key_str} has wrong dimensions: "
                f"{set(mpk.keys_by_dimension.keys())}"
            )
            assert mpk.keys_by_dimension["day"] == "2024-01-01"

        expected = {
            "day=2024-01-01|metric=x|source=A",
            "day=2024-01-01|metric=x|source=B",
            "day=2024-01-01|metric=y|source=A",
            "day=2024-01-01|metric=y|source=B",
        }
        assert set(upstream_keys) == expected


# ---------------------------------------------------------------------------
# End-to-end integration test
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_end_to_end_reconciliation(self):
        """Full pipeline reconciliation using YAML config and SQLite database.

        Verifies that all layers work together correctly:
        - Config loading with correct partition mappings
        - Database reads with duplicate handling and timestamp normalization
        - Reconciliation with correct topo order, staleness comparison,
          transitive propagation, and staleness mode support
        """
        graph = load_pipeline("/app/pipeline.yaml")
        store = SqliteMaterializationStore("/app/warehouse.db")

        reconciler = Reconciler(graph, store)
        result = reconciler.reconcile()

        # No assets should have unmaterialized partitions
        assert len(result.get_unmaterialized("raw")) == 0, (
            "raw should have no unmaterialized partitions"
        )
        assert len(result.get_unmaterialized("summary")) == 0, (
            "summary should have no unmaterialized partitions"
        )
        assert len(result.get_unmaterialized("report")) == 0, (
            "report should have no unmaterialized partitions"
        )

        # raw has no upstreams, nothing should be stale
        assert len(result.get_stale("raw")) == 0, (
            "raw (root asset) should have no stale partitions"
        )

        # summary uses "all" staleness mode:
        # Day 2024-01-01: all 4 raw partitions re-materialized -> STALE
        assert "2024-01-01" in result.get_stale("summary"), (
            "summary 2024-01-01 should be stale "
            "(all 4 upstream raw partitions were re-materialized)"
        )

        # Day 2024-01-02: raw partitions older than summary (after
        # timestamp normalization of the ms-format record) -> NOT stale
        assert "2024-01-02" not in result.get_stale("summary"), (
            "summary 2024-01-02 should NOT be stale "
            "(all upstream raw partitions are older after normalization)"
        )

        # Day 2024-01-03: only 1 of 4 raw partitions is newer
        # (the duplicate record's latest timestamp), all mode -> NOT stale
        assert "2024-01-03" not in result.get_stale("summary"), (
            "summary 2024-01-03 should NOT be stale "
            "(only 1 of 4 upstream is newer, 'all' mode requires all)"
        )

        # report uses "any" mode (default):
        # 2024-01-01: summary is stale -> transitive -> STALE
        assert "2024-01-01" in result.get_stale("report"), (
            "report 2024-01-01 should be stale "
            "(upstream summary is stale, transitive propagation)"
        )

        # 2024-01-02: summary not stale, timestamp older -> NOT stale
        assert "2024-01-02" not in result.get_stale("report"), (
            "report 2024-01-02 should NOT be stale"
        )

        # 2024-01-03: summary not stale, timestamp older -> NOT stale
        assert "2024-01-03" not in result.get_stale("report"), (
            "report 2024-01-03 should NOT be stale"
        )

        store.close()


# ---------------------------------------------------------------------------
# SQLite analytical views tests
# ---------------------------------------------------------------------------

class TestSQLiteViews:
    def test_v_latest_materializations_exists(self):
        """View v_latest_materializations must exist in the database."""
        conn = sqlite3.connect("/app/warehouse.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='view' AND name='v_latest_materializations'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "View v_latest_materializations does not exist"

    def test_v_latest_materializations_row_count(self):
        """Should have exactly one row per (asset_key, partition_key)."""
        conn = sqlite3.connect("/app/warehouse.db")
        cursor = conn.execute("SELECT COUNT(*) FROM v_latest_materializations")
        count = cursor.fetchone()[0]
        conn.close()
        # 12 raw partitions + 3 summary + 3 report = 18 unique (asset, partition) pairs
        assert count == 18, (
            f"Expected 18 rows (12 raw + 3 summary + 3 report), got {count}"
        )

    def test_v_latest_materializations_dedup(self):
        """Re-materialized partition should return the latest timestamp."""
        conn = sqlite3.connect("/app/warehouse.db")
        cursor = conn.execute(
            "SELECT normalized_ts FROM v_latest_materializations "
            "WHERE asset_key = 'raw' "
            "AND partition_key = 'day=2024-01-01|metric=x|source=A'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "Missing record for re-materialized partition"
        assert abs(row[0] - 1704326400.0) < 0.001, (
            f"Expected latest normalized_ts 1704326400.0, got {row[0]}"
        )

    def test_v_latest_materializations_ms_normalization(self):
        """Millisecond timestamp should be normalized to seconds in the view."""
        conn = sqlite3.connect("/app/warehouse.db")
        cursor = conn.execute(
            "SELECT normalized_ts FROM v_latest_materializations "
            "WHERE asset_key = 'raw' "
            "AND partition_key = 'day=2024-01-02|metric=y|source=B'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "Missing record for ms-timestamp partition"
        assert row[0] < 1e12, f"Timestamp not normalized from ms: {row[0]}"
        assert abs(row[0] - 1704067200.0) < 0.001, (
            f"Expected ~1704067200.0 after ms normalization, got {row[0]}"
        )

    def test_v_materialization_history_exists(self):
        """View v_materialization_history must exist in the database."""
        conn = sqlite3.connect("/app/warehouse.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='view' AND name='v_materialization_history'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "View v_materialization_history does not exist"

    def test_v_materialization_history_recency_rank(self):
        """Most recent record should have recency_rank = 1."""
        conn = sqlite3.connect("/app/warehouse.db")
        cursor = conn.execute(
            "SELECT normalized_ts, recency_rank FROM v_materialization_history "
            "WHERE asset_key = 'raw' "
            "AND partition_key = 'day=2024-01-01|metric=x|source=A' "
            "AND recency_rank = 1"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "No rank-1 record found for re-materialized partition"
        assert abs(row[0] - 1704326400.0) < 0.001, (
            f"Rank-1 record should have latest ts 1704326400.0, got {row[0]}"
        )

    def test_v_materialization_history_total_records(self):
        """Partitions with multiple materializations should show correct total_records."""
        conn = sqlite3.connect("/app/warehouse.db")
        cursor = conn.execute(
            "SELECT DISTINCT total_records FROM v_materialization_history "
            "WHERE asset_key = 'raw' "
            "AND partition_key = 'day=2024-01-01|metric=x|source=A'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "No history records found"
        assert row[0] == 2, (
            f"Expected total_records=2 for re-materialized partition, got {row[0]}"
        )


# ---------------------------------------------------------------------------
# Event audit tests (jq-produced output)
# ---------------------------------------------------------------------------

class TestEventAudit:
    def test_event_audit_exists(self):
        """The event_audit.json file must exist."""
        assert os.path.isfile("/app/event_audit.json"), (
            "/app/event_audit.json not found"
        )

    def test_event_audit_structure(self):
        """Event audit must contain all required top-level fields."""
        with open("/app/event_audit.json") as f:
            data = json.load(f)
        required = {
            "total_events", "events_by_level", "staleness_checks",
            "reported_total_stale", "reported_total_unmaterialized",
        }
        missing = required - set(data.keys())
        assert not missing, f"Missing fields in event_audit.json: {missing}"

    def test_event_audit_counts(self):
        """Event counts must match the actual log content."""
        with open("/app/event_audit.json") as f:
            data = json.load(f)
        assert data["total_events"] == 10, (
            f"Expected 10 total events, got {data['total_events']}"
        )
        assert data["events_by_level"].get("INFO") == 7, (
            f"Expected 7 INFO events, got {data['events_by_level'].get('INFO')}"
        )
        assert data["events_by_level"].get("DEBUG") == 3, (
            f"Expected 3 DEBUG events, got {data['events_by_level'].get('DEBUG')}"
        )

    def test_event_audit_staleness_checks(self):
        """Staleness check entries must be correctly extracted."""
        with open("/app/event_audit.json") as f:
            data = json.load(f)
        checks = data["staleness_checks"]
        assert len(checks) == 3, (
            f"Expected 3 staleness checks, got {len(checks)}"
        )
        assets = {c["asset"] for c in checks}
        assert assets == {"summary"}, (
            f"All staleness checks should be for 'summary', got {assets}"
        )
        for check in checks:
            assert check["result"] == "fresh", (
                f"Logged result should be 'fresh', got {check['result']}"
            )
            assert "upstream_resolved" in check, (
                "Each check must include upstream_resolved"
            )


# ---------------------------------------------------------------------------
# Reconciliation planner tests
# ---------------------------------------------------------------------------

class TestReconciliationPlan:
    def test_plan_exists(self):
        """The recon_plan.json file must exist."""
        assert os.path.isfile("/app/recon_plan.json"), (
            "/app/recon_plan.json not found"
        )

    def test_plan_structure(self):
        """Plan must contain all required fields."""
        with open("/app/recon_plan.json") as f:
            plan = json.load(f)
        required = {
            "stale_partitions", "total_cost", "budget",
            "budget_exceeded", "selected", "total_selected_cost",
        }
        missing = required - set(plan.keys())
        assert not missing, f"Missing fields in recon_plan.json: {missing}"

    def test_plan_stale_partitions(self):
        """Should identify exactly 2 stale partitions: summary and report for 2024-01-01."""
        with open("/app/recon_plan.json") as f:
            plan = json.load(f)
        stale = plan["stale_partitions"]
        assert len(stale) == 2, (
            f"Expected 2 stale partitions, got {len(stale)}: {stale}"
        )
        stale_set = {(s["asset"], s["partition"]) for s in stale}
        assert ("summary", "2024-01-01") in stale_set, (
            "summary:2024-01-01 should be stale"
        )
        assert ("report", "2024-01-01") in stale_set, (
            "report:2024-01-01 should be stale"
        )

    def test_plan_total_cost(self):
        """Total cost should be summary(50) + report(30) = 80."""
        with open("/app/recon_plan.json") as f:
            plan = json.load(f)
        assert abs(plan["total_cost"] - 80.0) < 0.01, (
            f"Expected total_cost=80.0, got {plan['total_cost']}"
        )

    def test_plan_budget_exceeded(self):
        """Budget should be exceeded (80 > 70)."""
        with open("/app/recon_plan.json") as f:
            plan = json.load(f)
        assert plan["budget_exceeded"] is True, (
            "budget_exceeded should be True (total_cost 80 > budget 70)"
        )
        assert plan["budget"] == 70, f"Expected budget=70, got {plan['budget']}"

    def test_plan_selected_within_budget(self):
        """Total selected cost must not exceed the budget."""
        with open("/app/recon_plan.json") as f:
            plan = json.load(f)
        assert plan["total_selected_cost"] <= plan["budget"], (
            f"Selected cost {plan['total_selected_cost']} exceeds "
            f"budget {plan['budget']}"
        )

    def test_plan_cascade_aware_selection(self):
        """The planner must select summary:2024-01-01 (highest impact, enables
        downstream refresh). Report should not be selected because adding it
        would exceed the budget (50+30=80 > 70)."""
        with open("/app/recon_plan.json") as f:
            plan = json.load(f)
        selected_set = {(s["asset"], s["partition"]) for s in plan["selected"]}
        assert ("summary", "2024-01-01") in selected_set, (
            "summary:2024-01-01 must be selected (highest downstream impact, "
            "cost 50 fits budget 70)"
        )
        # If report is selected, its upstream summary must also be selected
        if ("report", "2024-01-01") in selected_set:
            assert ("summary", "2024-01-01") in selected_set, (
                "report cannot be selected without its upstream summary "
                "(cascade-aware constraint)"
            )
            # And total must be within budget
            total = sum(s["cost"] for s in plan["selected"])
            assert total <= plan["budget"], (
                f"Selected total {total} exceeds budget {plan['budget']}"
            )
