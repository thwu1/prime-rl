"""
Tests for sharded concurrent map with profiling-driven analysis.

Verifies: sharded map correctness, profiling pipeline outputs (bench.db,
.prof files), and analysis report structure and content.
"""

import sys
import os
import json
import sqlite3
import threading
import pstats
import time

sys.path.insert(0, "/app")

import pytest


# ---------------------------------------------------------------------------
# Sharded map correctness tests
# ---------------------------------------------------------------------------

class TestShardedMapBasic:
    def test_import(self):
        from sharded_map import ShardedMap, ShardedWriteHandle, ShardedReadHandle

    def test_create(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        assert w is not None
        assert r is not None

    def test_insert_and_get(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        w.insert("hello", 1)
        w.publish()
        assert r.get("hello") == [1]

    def test_multi_value_insert(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        w.insert("k", 1)
        w.insert("k", 2)
        w.insert("k", 3)
        w.publish()
        assert sorted(r.get("k")) == [1, 2, 3]

    def test_multi_shard_keys(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        for i in range(100):
            w.insert(f"key_{i}", i)
        w.publish()
        assert r.len() == 100
        for i in range(100):
            vals = r.get(f"key_{i}")
            assert vals == [i], f"key_{i}: expected [{i}], got {vals}"

    def test_shard_for_key_consistent(self):
        from sharded_map import ShardedMap
        w, _ = ShardedMap.new(4)
        shard1 = w.shard_for_key("test_key")
        shard2 = w.shard_for_key("test_key")
        assert shard1 == shard2
        assert 0 <= shard1 < 4

    def test_shard_for_key_range(self):
        from sharded_map import ShardedMap
        w, _ = ShardedMap.new(8)
        for i in range(200):
            s = w.shard_for_key(f"key_{i}")
            assert 0 <= s < 8, f"Shard {s} out of range for key_{i}"

    def test_shard_distribution(self):
        """Keys are distributed across shards, not all in one."""
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        for i in range(200):
            w.insert(f"key_{i}", i)
        w.publish()
        shard_lens = r.shard_lens()
        assert len(shard_lens) == 4
        assert sum(shard_lens.values()) == 200
        for sid, count in shard_lens.items():
            assert count > 0, f"Shard {sid} has no keys"

    def test_single_shard(self):
        """num_shards=1 should work like a regular left-right map."""
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(1)
        w.insert("a", 1)
        w.insert("b", 2)
        w.publish()
        assert r.get("a") == [1]
        assert r.get("b") == [2]
        assert r.len() == 2
        sl = r.shard_lens()
        assert sl == {0: 2}

    def test_remove_value(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(2)
        w.insert("k", 1)
        w.insert("k", 2)
        w.publish()
        assert sorted(r.get("k")) == [1, 2]
        w.remove_value("k", 1)
        w.publish()
        assert r.get("k") == [2]

    def test_remove_entry(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(2)
        w.insert("k", 1)
        w.publish()
        w.remove_entry("k")
        w.publish()
        assert r.get("k") is None
        assert not r.contains_key("k")

    def test_clear(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        for i in range(50):
            w.insert(f"key_{i}", i)
        w.publish()
        assert r.len() == 50
        w.clear()
        w.publish()
        assert r.len() == 0

    def test_has_pending(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(2)
        w.insert("a", 1)
        w.publish()
        assert not w.has_pending()
        w.insert("b", 2)
        assert w.has_pending()

    def test_contains_key(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        w.insert("exists", 1)
        w.publish()
        assert r.contains_key("exists")
        assert not r.contains_key("nope")

    def test_keys(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        w.insert("a", 1)
        w.insert("b", 2)
        w.insert("c", 3)
        w.publish()
        assert sorted(r.keys()) == ["a", "b", "c"]

    def test_clone_reader(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(2)
        w.insert("x", 42)
        w.publish()
        r2 = r.clone()
        assert r2.get("x") == [42]
        w.insert("y", 99)
        w.publish()
        assert sorted(r2.keys()) == ["x", "y"]

    def test_destroy(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(2)
        w.insert("a", 1)
        w.publish()
        assert r.get("a") == [1]
        w.destroy()

    def test_multi_publish_cycles(self):
        """Data stays correct across many publish cycles."""
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        for i in range(50):
            w.insert("key", i)
            w.publish()
        vals = r.get("key")
        assert sorted(vals) == list(range(50))

    def test_get_returns_copy(self):
        """get() must return a copy, not a reference to internal state."""
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(2)
        w.insert("a", 1)
        w.publish()
        vals = r.get("a")
        vals.append(999)
        assert r.get("a") == [1]


class TestShardedMapConcurrent:
    def test_concurrent_reads(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        for i in range(100):
            w.insert(f"key_{i}", i)
        w.publish()

        errors = []
        def reader_fn(r_clone, tid):
            try:
                for _ in range(200):
                    for i in range(0, 100, 10):
                        vals = r_clone.get(f"key_{i}")
                        assert vals == [i], f"Thread {tid}: key_{i} = {vals}"
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(4):
            t = threading.Thread(target=reader_fn, args=(r.clone(), i))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert errors == [], f"Errors: {errors}"

    def test_concurrent_writer_reader(self):
        from sharded_map import ShardedMap
        w, r = ShardedMap.new(4)
        stop = threading.Event()
        errors = []

        def reader_fn(r_clone, tid):
            try:
                while not stop.is_set():
                    length = r_clone.len()
                    assert length >= 0
                    time.sleep(0.001)
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(4):
            t = threading.Thread(target=reader_fn, args=(r.clone(), i))
            threads.append(t)
            t.start()

        for i in range(200):
            w.insert(f"k_{i}", i)
            if i % 10 == 0:
                w.publish()
        w.publish()

        stop.set()
        for t in threads:
            t.join(timeout=10)
        assert errors == [], f"Errors: {errors}"


# ---------------------------------------------------------------------------
# Profiling pipeline output tests
# ---------------------------------------------------------------------------

class TestProfilingOutputs:
    def test_bench_db_exists(self):
        assert os.path.exists("/app/output/bench.db"), \
            "bench.db not found at /app/output/bench.db"

    def test_bench_db_tables(self):
        conn = sqlite3.connect("/app/output/bench.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        required = {
            "workload_results",
            "shard_distribution",
            "profile_stats",
            "memory_snapshots",
        }
        missing = required - tables
        assert not missing, f"Missing tables in bench.db: {missing}"

    def test_workload_results_data(self):
        conn = sqlite3.connect("/app/output/bench.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM workload_results")
        count = cursor.fetchone()[0]
        conn.close()
        # 4 workloads x 5 shard counts = 20 rows minimum
        assert count >= 20, f"Expected >= 20 workload_results rows, got {count}"

    def test_workload_results_columns(self):
        conn = sqlite3.connect("/app/output/bench.db")
        cursor = conn.cursor()
        cursor.execute("SELECT workload_name, num_shards, total_ops, "
                       "elapsed_seconds, throughput_ops_per_sec "
                       "FROM workload_results LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "No data in workload_results"
        assert row[2] > 0, "total_ops must be positive"
        assert row[3] > 0, "elapsed_seconds must be positive"
        assert row[4] > 0, "throughput must be positive"

    def test_shard_distribution_data(self):
        conn = sqlite3.connect("/app/output/bench.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM shard_distribution")
        count = cursor.fetchone()[0]
        conn.close()
        # 4 workloads x (1+2+4+8+16) = 4 x 31 = 124 rows minimum
        assert count >= 100, f"Expected >= 100 shard_distribution rows, got {count}"

    def test_profile_stats_data(self):
        conn = sqlite3.connect("/app/output/bench.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM profile_stats")
        count = cursor.fetchone()[0]
        conn.close()
        assert count > 0, "No profile_stats data"

    def test_memory_data(self):
        conn = sqlite3.connect("/app/output/bench.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM memory_snapshots")
        count = cursor.fetchone()[0]
        cursor.execute("SELECT peak_memory_bytes FROM memory_snapshots LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        assert count >= 20, f"Expected >= 20 memory_snapshots rows, got {count}"
        assert row[0] > 0, "peak_memory_bytes must be positive"

    def test_prof_files_exist(self):
        """At least 20 .prof files should exist (4 workloads x 5 shard counts)."""
        output_dir = "/app/output"
        assert os.path.isdir(output_dir), "/app/output directory not found"
        prof_files = [f for f in os.listdir(output_dir) if f.endswith(".prof")]
        assert len(prof_files) >= 20, \
            f"Expected >= 20 .prof files, got {len(prof_files)}: {prof_files[:5]}"

    def test_prof_files_loadable(self):
        """cProfile .prof files should be loadable with pstats."""
        output_dir = "/app/output"
        prof_files = [f for f in os.listdir(output_dir) if f.endswith(".prof")]
        assert len(prof_files) > 0, "No .prof files found"
        stats = pstats.Stats(os.path.join(output_dir, prof_files[0]))
        assert len(stats.stats) > 0, "Profile has no stats entries"


# ---------------------------------------------------------------------------
# Report tests
# ---------------------------------------------------------------------------

class TestReport:
    @pytest.fixture
    def report(self):
        path = "/app/output/report.json"
        assert os.path.exists(path), "report.json not found at /app/output/"
        with open(path) as f:
            return json.load(f)

    def test_report_has_workloads(self, report):
        assert "workloads" in report
        assert len(report["workloads"]) >= 4, \
            f"Expected >= 4 workloads, got {len(report['workloads'])}"

    def test_report_workload_structure(self, report):
        for wl_name, wl_data in report["workloads"].items():
            assert "shard_counts_tested" in wl_data, \
                f"{wl_name}: missing shard_counts_tested"
            assert "throughput" in wl_data, f"{wl_name}: missing throughput"
            assert "distribution_cv" in wl_data, \
                f"{wl_name}: missing distribution_cv"
            assert "peak_memory_bytes" in wl_data, \
                f"{wl_name}: missing peak_memory_bytes"

    def test_report_throughput_positive(self, report):
        for wl_name, wl_data in report["workloads"].items():
            for sc, tp in wl_data["throughput"].items():
                assert tp > 0, \
                    f"{wl_name} shard_count={sc}: throughput must be positive"

    def test_report_cv_reasonable(self, report):
        for wl_name, wl_data in report["workloads"].items():
            for sc, cv in wl_data["distribution_cv"].items():
                assert 0 <= cv <= 3, \
                    f"{wl_name} shard_count={sc}: CV={cv} out of [0, 3] range"

    def test_report_single_shard_cv_zero(self, report):
        """With 1 shard, coefficient of variation should be 0."""
        for wl_name, wl_data in report["workloads"].items():
            if "1" in wl_data["distribution_cv"]:
                cv = wl_data["distribution_cv"]["1"]
                assert cv == 0.0, \
                    f"{wl_name}: CV for 1 shard should be 0, got {cv}"

    def test_report_has_optimal(self, report):
        assert "optimal_shard_count" in report
        opt = report["optimal_shard_count"]
        assert isinstance(opt, int), \
            f"optimal_shard_count must be int, got {type(opt)}"
        assert opt >= 1, "optimal_shard_count must be >= 1"

    def test_report_has_recommendation(self, report):
        assert "recommendation" in report
        rec = report["recommendation"]
        assert isinstance(rec, str)
        assert len(rec) >= 50, \
            f"Recommendation too short ({len(rec)} chars), expected >= 50"

    def test_report_has_crossover(self, report):
        assert "crossover_analysis" in report
        ca = report["crossover_analysis"]
        assert isinstance(ca, str)
        assert len(ca) >= 50, \
            f"Crossover analysis too short ({len(ca)} chars), expected >= 50"

    def test_report_memory_positive(self, report):
        for wl_name, wl_data in report["workloads"].items():
            for sc, mem in wl_data["peak_memory_bytes"].items():
                assert mem > 0, \
                    f"{wl_name} shard_count={sc}: memory must be positive"
