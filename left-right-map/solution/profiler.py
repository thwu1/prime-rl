"""
Profiling pipeline: benchmarks the sharded map under workloads from workloads.json
for shard counts [1, 2, 4, 8, 16] using cProfile, pstats, tracemalloc, and sqlite3.
"""

import cProfile
import pstats
import tracemalloc
import sqlite3
import json
import sys
import os
import time
import random
import io

sys.path.insert(0, "/app")
from sharded_map import ShardedMap

SHARD_COUNTS = [1, 2, 4, 8, 16]
OUTPUT_DIR = "/app/output"


def generate_workload(spec):
    """Generate a list of (op_type, key, value) tuples from a workload spec."""
    rng = random.Random(spec["seed"])
    ops = []
    num_keys = spec["num_keys"]
    num_ops = spec["num_operations"]
    read_frac = spec["read_fraction"]
    dist = spec["key_distribution"]

    for _ in range(num_ops):
        if dist == "uniform":
            key = f"key_{rng.randint(0, num_keys - 1)}"
        elif dist == "zipf":
            alpha = spec.get("zipf_alpha", 1.2)
            # Inverse-transform Zipf approximation
            u = rng.random()
            raw = u ** (1.0 / max(1.0 - alpha, 0.01))
            key_idx = int(raw * num_keys) % num_keys
            key = f"key_{key_idx}"
        elif dist == "hotspot":
            hot_frac = spec.get("hot_fraction", 0.01)
            hot_weight = spec.get("hot_weight", 0.9)
            hot_keys = max(1, int(num_keys * hot_frac))
            if rng.random() < hot_weight:
                key = f"key_{rng.randint(0, hot_keys - 1)}"
            else:
                key = f"key_{rng.randint(hot_keys, num_keys - 1)}"
        else:
            key = f"key_{rng.randint(0, num_keys - 1)}"

        if rng.random() < read_frac:
            ops.append(("read", key, None))
        else:
            ops.append(("write", key, rng.randint(0, 999999)))

    return ops


def run_workload(w, r, ops, publish_interval=100):
    """Execute a workload against a sharded map."""
    write_count = 0
    for op_type, key, value in ops:
        if op_type == "read":
            r.get(key)
        else:
            w.insert(key, value)
            write_count += 1
            if write_count % publish_interval == 0:
                w.publish()
    # Final publish to make all writes visible
    w.publish()


def setup_database(db_path):
    """Create SQLite database with required schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""CREATE TABLE IF NOT EXISTS workload_results (
        workload_name TEXT,
        num_shards INTEGER,
        total_ops INTEGER,
        elapsed_seconds REAL,
        throughput_ops_per_sec REAL
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS shard_distribution (
        workload_name TEXT,
        num_shards INTEGER,
        shard_id INTEGER,
        key_count INTEGER
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS profile_stats (
        workload_name TEXT,
        num_shards INTEGER,
        function_name TEXT,
        cumulative_time REAL,
        call_count INTEGER
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS memory_snapshots (
        workload_name TEXT,
        num_shards INTEGER,
        peak_memory_bytes INTEGER
    )""")

    conn.commit()
    return conn


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open("/app/workloads.json") as f:
        workloads = json.load(f)

    db_path = os.path.join(OUTPUT_DIR, "bench.db")
    conn = setup_database(db_path)
    cursor = conn.cursor()

    for workload in workloads:
        wl_name = workload["name"]
        ops = generate_workload(workload)

        for num_shards in SHARD_COUNTS:
            print(f"Profiling {wl_name} with {num_shards} shard(s)...")

            w, r = ShardedMap.new(num_shards)

            # Start tracemalloc
            tracemalloc.start()

            # Profile with cProfile
            prof = cProfile.Profile()
            start_time = time.monotonic()
            prof.enable()
            run_workload(w, r, ops)
            prof.disable()
            elapsed = time.monotonic() - start_time

            # Capture peak memory
            _, peak_mem = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            # Save .prof file
            prof_file = os.path.join(
                OUTPUT_DIR, f"{wl_name}_{num_shards}.prof"
            )
            prof.dump_stats(prof_file)

            # Extract pstats: top 20 by cumulative time
            stream = io.StringIO()
            stats = pstats.Stats(prof, stream=stream)
            stats.sort_stats("cumulative")

            stats_list = []
            for func_key, (cc, nc, tt, ct, callers) in stats.stats.items():
                fname = f"{func_key[0]}:{func_key[1]}:{func_key[2]}"
                stats_list.append((fname, ct, cc))
            stats_list.sort(key=lambda x: -x[1])

            # Record shard distribution
            shard_lens = r.shard_lens()

            # Compute throughput
            throughput = len(ops) / elapsed if elapsed > 0 else 0.0

            # Insert into database
            cursor.execute(
                "INSERT INTO workload_results VALUES (?, ?, ?, ?, ?)",
                (wl_name, num_shards, len(ops), elapsed, throughput),
            )

            for shard_id in range(num_shards):
                key_count = shard_lens.get(shard_id, 0)
                cursor.execute(
                    "INSERT INTO shard_distribution VALUES (?, ?, ?, ?)",
                    (wl_name, num_shards, shard_id, key_count),
                )

            for fname, ct, cc in stats_list[:20]:
                cursor.execute(
                    "INSERT INTO profile_stats VALUES (?, ?, ?, ?, ?)",
                    (wl_name, num_shards, fname, ct, cc),
                )

            cursor.execute(
                "INSERT INTO memory_snapshots VALUES (?, ?, ?)",
                (wl_name, num_shards, peak_mem),
            )

            conn.commit()

            # Cleanup
            w.destroy()

    conn.close()
    print(f"Profiling complete. Results in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
