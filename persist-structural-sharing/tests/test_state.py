"""
Tests for SQLite-backed pool store with cross-pool deduplication
and structural diff engine.

"""

import json
import os
import sqlite3
import subprocess
import sys

sys.path.insert(0, "/app")

from pvec import PersistentVector
from serialize import serialize_pool, deserialize_pool


# ---------------------------------------------------------------------------
# Schema verification
# ---------------------------------------------------------------------------


class TestSchema:
    """The PoolStore must create the prescribed relational schema."""

    def test_required_tables(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_schema_tables.db"
        try:
            store = PoolStore(db_path)
            conn = sqlite3.connect(db_path)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for t in ("nodes", "leaf_data", "inner_children", "vectors"):
                assert t in tables, f"Missing table: {t}"
            conn.close()
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_nodes_columns(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_schema_cols.db"
        try:
            store = PoolStore(db_path)
            conn = sqlite3.connect(db_path)
            cols = {
                row[1] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()
            }
            assert "id" in cols
            assert "node_type" in cols
            assert "content_hash" in cols
            conn.close()
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_content_hash_unique_constraint(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_schema_uniq.db"
        try:
            store = PoolStore(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO nodes (node_type, content_hash) VALUES ('leaf', 'hash_a')"
            )
            try:
                conn.execute(
                    "INSERT INTO nodes (node_type, content_hash) VALUES ('leaf', 'hash_a')"
                )
                conn.commit()
                assert False, "content_hash should be UNIQUE"
            except sqlite3.IntegrityError:
                pass
            conn.close()
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# Import / export round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Import then export must reproduce the original vector data."""

    def test_small_vectors(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_rt_small.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector.of(1, 2, 3, 4)
            v2 = v1.push_back(5).push_back(6)
            v3 = v2.set(0, 999)
            pool = serialize_pool({"v1": v1, "v2": v2, "v3": v3})
            store.import_pool(pool, "test")
            exported = store.export_all()
            r = deserialize_pool(exported)
            assert r["v1"].to_list() == [1, 2, 3, 4]
            assert r["v2"].to_list() == [1, 2, 3, 4, 5, 6]
            assert r["v3"].to_list() == [999, 2, 3, 4, 5, 6]
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_empty_vector(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_rt_empty.db"
        try:
            store = PoolStore(db_path)
            pool = serialize_pool({"v": PersistentVector()})
            store.import_pool(pool, "test")
            exported = store.export_all()
            r = deserialize_pool(exported)
            assert r["v"].to_list() == []
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_deep_tree(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_rt_deep.db"
        try:
            store = PoolStore(db_path)
            v = PersistentVector()
            for i in range(50):
                v = v.push_back(i)
            pool = serialize_pool({"deep": v})
            store.import_pool(pool, "test")
            exported = store.export_all()
            r = deserialize_pool(exported)
            assert r["deep"].to_list() == list(range(50))
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_multi_pool_import(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_rt_multi.db"
        try:
            store = PoolStore(db_path)
            pool1 = serialize_pool({"letters": PersistentVector.of("a", "b", "c", "d")})
            pool2 = serialize_pool({"numbers": PersistentVector.of(10, 20, 30, 40)})
            store.import_pool(pool1, "pool1")
            store.import_pool(pool2, "pool2")
            exported = store.export_all()
            r = deserialize_pool(exported)
            assert r["letters"].to_list() == ["a", "b", "c", "d"]
            assert r["numbers"].to_list() == [10, 20, 30, 40]
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_export_vectors_subset(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_rt_subset.db"
        try:
            store = PoolStore(db_path)
            pool = serialize_pool({
                "alpha": PersistentVector.of(1, 2, 3, 4),
                "beta": PersistentVector.of(5, 6, 7, 8),
            })
            store.import_pool(pool, "test")
            exported = store.export_vectors(["alpha"])
            assert "alpha" in exported["vectors"]
            assert "beta" not in exported["vectors"]
            r = deserialize_pool(exported)
            assert r["alpha"].to_list() == [1, 2, 3, 4]
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# Cross-pool content-based deduplication
# ---------------------------------------------------------------------------


class TestCrossPoolDedup:

    def test_identical_pools_no_growth(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_dedup_ident.db"
        try:
            store = PoolStore(db_path)
            v = PersistentVector.of(1, 2, 3, 4, 5)
            pool1 = serialize_pool({"v": v})
            pool2 = serialize_pool({"v_copy": v})
            store.import_pool(pool1, "p1")
            stats1 = store.stats()
            store.import_pool(pool2, "p2")
            stats2 = store.stats()
            assert stats2["total_nodes"] == stats1["total_nodes"], (
                f"Identical content should share all nodes: "
                f"{stats1['total_nodes']} after p1, {stats2['total_nodes']} after p2"
            )
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_overlapping_pools_share_subtrees(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_dedup_overlap.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector.of(1, 2, 3, 4)
            v2 = v1.push_back(5)
            pool1 = serialize_pool({"base": v1})
            pool2 = serialize_pool({"extended": v2})
            store.import_pool(pool1, "p1")
            store.import_pool(pool2, "p2")
            stats = store.stats()
            sum_individual = len(pool1["nodes"]) + len(pool2["nodes"])
            assert stats["total_nodes"] < sum_individual, (
                f"Cross-pool dedup should reduce nodes: "
                f"{stats['total_nodes']} >= {sum_individual}"
            )
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_five_overlapping_pools_significant_reduction(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_dedup_five.db"
        try:
            store = PoolStore(db_path)
            total_raw_nodes = 0
            for i in range(5):
                v = PersistentVector()
                versions = {}
                for j in range(10):
                    v = v.push_back(j)
                    versions[f"pool{i}_v{j}"] = v
                pool = serialize_pool(versions)
                total_raw_nodes += len(pool["nodes"])
                store.import_pool(pool, f"pool_{i}")
            stats = store.stats()
            assert stats["total_nodes"] < total_raw_nodes * 0.5
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# Sharing preservation after round-trip
# ---------------------------------------------------------------------------


class TestSharingPreservation:

    def test_tail_sharing(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_share_tail.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector.of(1, 2, 3, 4)
            v2 = v1.push_back(5).push_back(6)
            v3 = v2.set(0, 999)
            pool = serialize_pool({"v2": v2, "v3": v3})
            store.import_pool(pool, "test")
            exported = store.export_all()
            r = deserialize_pool(exported)
            assert r["v2"].tail is r["v3"].tail
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_root_sharing_after_tail_set(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_share_root.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector.of(1, 2, 3, 4, 5)
            v2 = v1.set(4, 999)  # index 4 is in the tail
            pool = serialize_pool({"v1": v1, "v2": v2})
            store.import_pool(pool, "test")
            exported = store.export_all()
            r = deserialize_pool(exported)
            assert r["v1"].root is r["v2"].root
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_cross_pool_sharing(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_share_xpool.db"
        try:
            store = PoolStore(db_path)
            v = PersistentVector.of(1, 2, 3, 4, 5)
            pool1 = serialize_pool({"v_a": v})
            pool2 = serialize_pool({"v_b": v})
            store.import_pool(pool1, "p1")
            store.import_pool(pool2, "p2")
            exported = store.export_all()
            r = deserialize_pool(exported)
            assert r["v_a"].root is r["v_b"].root
            assert r["v_a"].tail is r["v_b"].tail
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# Integrity verification
# ---------------------------------------------------------------------------


class TestIntegrity:

    def test_clean_database(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_int_clean.db"
        try:
            store = PoolStore(db_path)
            v = PersistentVector.of(1, 2, 3, 4, 5)
            pool = serialize_pool({"v": v})
            store.import_pool(pool, "test")
            report = store.verify_integrity()
            assert report["orphaned_nodes"] == 0
            assert report["duplicate_content"] == 0
            assert report["invalid_refs"] == 0
            assert report["total_nodes"] > 0
            assert report["total_vectors"] == 1
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_detects_orphaned_node(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_int_orphan.db"
        try:
            store = PoolStore(db_path)
            v = PersistentVector.of(1, 2, 3, 4, 5)
            pool = serialize_pool({"v": v})
            store.import_pool(pool, "test")
            store.close()

            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO nodes (node_type, content_hash) "
                "VALUES ('leaf', 'orphan_deadbeef_xyz')"
            )
            conn.commit()
            conn.close()

            store2 = PoolStore(db_path)
            report = store2.verify_integrity()
            assert report["orphaned_nodes"] >= 1
            store2.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_stats_keys(self):
        from pool_store import PoolStore

        db_path = "/tmp/test_stats_keys.db"
        try:
            store = PoolStore(db_path)
            v = PersistentVector.of(1, 2, 3, 4, 5)
            pool = serialize_pool({"v": v})
            store.import_pool(pool, "test")
            stats = store.stats()
            for key in (
                "total_nodes", "leaf_nodes", "inner_nodes",
                "total_vectors", "total_edges",
            ):
                assert key in stats, f"Missing key in stats: {key}"
            assert stats["total_nodes"] == stats["leaf_nodes"] + stats["inner_nodes"]
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# Structural diff — correctness
# ---------------------------------------------------------------------------


class TestStructuralDiff:
    """The diff engine must produce correct element-level diffs."""

    def test_identical_vectors_empty_diff(self):
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_diff_ident.db"
        try:
            store = PoolStore(db_path)
            v = PersistentVector.of(1, 2, 3, 4, 5)
            pool = serialize_pool({"va": v, "vb": v})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            result = differ.diff("va", "vb")
            assert result["modified"] == {}
            assert result["added"] == {}
            assert result["removed"] == {}
            assert result["stats"]["nodes_skipped"] >= 1
            assert result["stats"]["nodes_visited"] == 0
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_single_set_modification(self):
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_diff_set.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector.of(1, 2, 3, 4, 5)
            v2 = v1.set(2, 999)
            pool = serialize_pool({"v1": v1, "v2": v2})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            result = differ.diff("v1", "v2")
            assert result["modified"] == {2: [3, 999]}
            assert result["added"] == {}
            assert result["removed"] == {}
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_tail_modification(self):
        """set() on a tail element should be detected; tree root skipped."""
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_diff_tail.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector.of(1, 2, 3, 4, 5)
            v2 = v1.set(4, 999)  # index 4 is in the tail
            pool = serialize_pool({"v1": v1, "v2": v2})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            result = differ.diff("v1", "v2")
            assert result["modified"] == {4: [5, 999]}
            assert result["added"] == {}
            assert result["removed"] == {}
            # Tree root is shared so should be skipped
            assert result["stats"]["nodes_skipped"] >= 1
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_push_back_additions(self):
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_diff_push.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector.of(1, 2, 3, 4, 5, 6, 7, 8)
            v2 = v1.push_back(9).push_back(10)
            pool = serialize_pool({"v1": v1, "v2": v2})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            result = differ.diff("v1", "v2")
            assert result["modified"] == {}
            assert result["added"] == {8: 9, 9: 10}
            assert result["removed"] == {}
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_multiple_set_modifications(self):
        """set() at two widely separated indices in a 25-element vector."""
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_diff_multi.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector()
            for i in range(25):
                v1 = v1.push_back(i)
            v2 = v1.set(0, "a").set(12, "b")
            pool = serialize_pool({"v1": v1, "v2": v2})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            result = differ.diff("v1", "v2")
            assert result["modified"][0] == [0, "a"]
            assert result["modified"][12] == [12, "b"]
            assert len(result["modified"]) == 2
            assert result["added"] == {}
            assert result["removed"] == {}
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_diff_symmetry(self):
        """diff(a,b) modified entries should be mirrored in diff(b,a)."""
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_diff_sym.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector.of(1, 2, 3, 4, 5, 6, 7, 8)
            v2 = v1.set(1, 999).push_back(9)
            pool = serialize_pool({"v1": v1, "v2": v2})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            ab = differ.diff("v1", "v2")
            ba = differ.diff("v2", "v1")
            # Modified entries should be mirrored
            for idx, (old, new) in ab["modified"].items():
                assert idx in ba["modified"]
                assert ba["modified"][idx] == [new, old]
            # Added/removed should swap
            assert ab["added"] == ba["removed"]
            assert ab["removed"] == ba["added"]
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_deep_tree_sparse_diff(self):
        """A single set on a 50-element vector should produce one modification."""
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_diff_deep.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector()
            for i in range(50):
                v1 = v1.push_back(i)
            v2 = v1.set(0, "x")
            pool = serialize_pool({"v1": v1, "v2": v2})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            result = differ.diff("v1", "v2")
            assert result["modified"] == {0: [0, "x"]}
            assert result["added"] == {}
            assert result["removed"] == {}
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# Structural diff — efficiency
# ---------------------------------------------------------------------------


class TestDiffEfficiency:
    """The diff must exploit structural sharing for sublinear traversal."""

    def test_sublinear_visits_for_set(self):
        """For a 50-element vector with one set(), visited << total nodes."""
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_diff_eff.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector()
            for i in range(50):
                v1 = v1.push_back(i)
            v2 = v1.set(0, "x")
            pool = serialize_pool({"v1": v1, "v2": v2})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            result = differ.diff("v1", "v2")
            s = result["stats"]
            assert s["nodes_visited"] < s["total_reachable"], (
                f"Visited {s['nodes_visited']} but total reachable is "
                f"{s['total_reachable']}; expected sublinear traversal"
            )
            assert s["nodes_skipped"] >= 3, (
                f"Expected at least 3 skipped subtrees, got {s['nodes_skipped']}"
            )
            # Visited should be well under half of reachable
            assert s["nodes_visited"] < s["total_reachable"] * 0.5
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_sharing_ratio_identical(self):
        """Structurally identical vectors should have sharing_ratio == 1.0."""
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_sr_ident.db"
        try:
            store = PoolStore(db_path)
            v = PersistentVector.of(1, 2, 3, 4, 5)
            pool = serialize_pool({"va": v, "vb": v})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            assert differ.sharing_ratio("va", "vb") == 1.0
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_sharing_ratio_related_vs_unrelated(self):
        """Related versions should share more structure than unrelated vectors."""
        from pool_store import PoolStore
        from diff_engine import StructuralDiff

        db_path = "/tmp/test_sr_compare.db"
        try:
            store = PoolStore(db_path)
            v1 = PersistentVector()
            for i in range(25):
                v1 = v1.push_back(i)
            v2 = v1.set(0, 999)  # closely related
            v3 = PersistentVector()
            for i in range(25):
                v3 = v3.push_back(i + 100)  # unrelated content
            pool = serialize_pool({"v1": v1, "v2": v2, "v3": v3})
            store.import_pool(pool, "test")
            differ = StructuralDiff(store)
            ratio_related = differ.sharing_ratio("v1", "v2")
            ratio_unrelated = differ.sharing_ratio("v1", "v3")
            assert ratio_related > 0.3, (
                f"Related vectors should share >30% structure: {ratio_related}"
            )
            assert ratio_related > ratio_unrelated, (
                f"Related {ratio_related} should exceed unrelated {ratio_unrelated}"
            )
            store.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# CLI compact pipeline
# ---------------------------------------------------------------------------


class TestCompactCLI:
    """The compact script must produce correct output with diff summary."""

    @classmethod
    def setup_class(cls):
        for f in ["/app/compacted.db", "/app/report.json", "/app/exported_pool.json"]:
            if os.path.exists(f):
                os.unlink(f)
        cls.result = subprocess.run(
            ["/app/compact"],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_compact_succeeds(self):
        assert self.result.returncode == 0, (
            f"compact failed (rc={self.result.returncode}):\n{self.result.stderr}"
        )

    def test_report_format(self):
        assert os.path.exists("/app/report.json"), "report.json not created"
        with open("/app/report.json") as f:
            report = json.load(f)
        for key in (
            "total_raw_nodes", "compacted_nodes", "reduction_pct",
            "vectors_imported", "diff_summary",
        ):
            assert key in report, f"Missing key in report: {key}"
        assert report["compacted_nodes"] < report["total_raw_nodes"]

    def test_compacted_db_integrity(self):
        from pool_store import PoolStore

        assert os.path.exists("/app/compacted.db"), "compacted.db not created"
        store = PoolStore("/app/compacted.db")
        report = store.verify_integrity()
        assert report["orphaned_nodes"] == 0
        assert report["duplicate_content"] == 0
        assert report["invalid_refs"] == 0
        store.close()

    def test_all_vectors_preserved(self):
        from pool_store import PoolStore

        conn = sqlite3.connect("/app/snapshots.db")
        rows = conn.execute(
            "SELECT name, pool_json FROM raw_pools ORDER BY id"
        ).fetchall()
        conn.close()

        original = {}
        for pool_name, pool_json_str in rows:
            pool = json.loads(pool_json_str)
            dvecs = deserialize_pool(pool)
            for vname, vec in dvecs.items():
                original[vname] = vec.to_list()

        store = PoolStore("/app/compacted.db")
        exported = store.export_all()
        compacted = deserialize_pool(exported)
        store.close()

        for vname, expected in original.items():
            assert vname in compacted, f"Vector '{vname}' missing after compaction"
            assert compacted[vname].to_list() == expected

    def test_diff_summary_present(self):
        """Report must include structural diff results for version pairs."""
        with open("/app/report.json") as f:
            report = json.load(f)
        ds = report["diff_summary"]
        assert isinstance(ds, dict)
        assert len(ds) > 0, "diff_summary should have at least one entry"
        # Check structure of entries
        for label, entry in ds.items():
            assert "nodes_visited" in entry
            assert "nodes_skipped" in entry
            assert "->" in label, f"Pair label should use '->' separator: {label}"

    def test_uses_sqlite3_cli(self):
        with open("/app/compact", "r") as f:
            content = f.read()
        assert "sqlite3" in content, "compact script must use sqlite3 CLI"

    def test_uses_jq(self):
        with open("/app/compact", "r") as f:
            content = f.read()
        assert "jq" in content, "compact script must use jq for JSON validation"

    def test_uses_awk(self):
        with open("/app/compact", "r") as f:
            content = f.read()
        assert "awk" in content, "compact script must use awk for formatted output"
