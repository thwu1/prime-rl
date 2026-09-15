#!/usr/bin/env python3
"""Generate benchmarks.db SQLite database with benchmark comparisons."""
import sys
sys.path.insert(0, '/app')

import sqlite3
import time
import numpy as np

from mask_base import FullMask
from masks import CausalMask, SlidingWindowMask, ChunkwiseMask, PrefixLMMask
from compound_masks import IntersectionMask, LocalGlobalMask
from reference import naive_masked_attention
from engine import tiled_attention


def main():
    # Create database from schema DDL
    with open('/app/db_schema.sql', 'r') as f:
        ddl = f.read()

    conn = sqlite3.connect('/app/benchmarks.db')
    conn.executescript(ddl)

    # Define masks and configurations
    masks = [
        ('FullMask', FullMask()),
        ('CausalMask', CausalMask()),
        ('SlidingWindowMask', SlidingWindowMask(10, 4)),
        ('ChunkwiseMask', ChunkwiseMask(8, 2)),
        ('PrefixLMMask', PrefixLMMask(10)),
        ('IntersectionMask', IntersectionMask(CausalMask(), SlidingWindowMask(10, 0))),
        ('LocalGlobalMask', LocalGlobalMask(5, 3)),
    ]

    configs = [
        (1, 1, 32, 8, 8, 8),
        (2, 2, 64, 16, 16, 16),
        (1, 1, 128, 8, 32, 16),
    ]

    np.random.seed(42)

    # Benchmark runs
    for mask_name, mask_obj in masks:
        for B, H, T, D, tq, tk in configs:
            q = np.random.randn(B, H, T, D).astype(np.float64)
            k_arr = np.random.randn(B, H, T, D).astype(np.float64)
            v = np.random.randn(B, H, T, D).astype(np.float64)

            t0 = time.perf_counter()
            ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj)
            naive_time = time.perf_counter() - t0

            t0 = time.perf_counter()
            tiled_out, tiled_lse = tiled_attention(
                q, k_arr, v, mask_obj, tile_q=tq, tile_k=tk
            )
            tiled_time = time.perf_counter() - t0

            max_out_err = float(np.max(np.abs(tiled_out - ref_out)))
            valid = np.isfinite(ref_lse)
            if np.any(valid):
                max_lse_err = float(
                    np.max(np.abs(tiled_lse[valid] - ref_lse[valid]))
                )
            else:
                max_lse_err = 0.0
            correct = 1 if max_out_err <= 1e-10 else 0
            speedup = naive_time / max(tiled_time, 1e-12)

            conn.execute(
                """INSERT INTO benchmark_runs
                   (mask_type, batch_size, num_heads, seq_len, head_dim,
                    tile_q, tile_k, naive_time_sec, tiled_time_sec, speedup,
                    max_output_error, max_lse_error, correct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mask_name, B, H, T, D, tq, tk, naive_time, tiled_time,
                 speedup, max_out_err, max_lse_err, correct)
            )

    # Mask call counts
    T_test = 64
    tq_test, tk_test = 16, 16
    n_q_tiles = (T_test + tq_test - 1) // tq_test
    n_k_tiles = (T_test + tk_test - 1) // tk_test
    total_pairs = n_q_tiles * n_k_tiles

    q = np.random.randn(1, 1, T_test, 8).astype(np.float64)
    k_arr = np.random.randn(1, 1, T_test, 8).astype(np.float64)
    v = np.random.randn(1, 1, T_test, 8).astype(np.float64)

    mask_factories = [
        ('FullMask', FullMask),
        ('CausalMask', CausalMask),
        ('SlidingWindowMask', lambda: SlidingWindowMask(10, 4)),
        ('ChunkwiseMask', lambda: ChunkwiseMask(8, 2)),
        ('PrefixLMMask', lambda: PrefixLMMask(10)),
    ]

    for mask_name, factory in mask_factories:
        mask_obj = factory()
        call_count = [0]
        original_mask = mask_obj.mask

        def counting_mask(*args, _orig=original_mask, _cnt=call_count, **kw):
            _cnt[0] += 1
            return _orig(*args, **kw)

        mask_obj.mask = counting_mask
        tiled_attention(q, k_arr, v, mask_obj, tile_q=tq_test, tile_k=tk_test)

        conn.execute(
            """INSERT INTO mask_call_counts
               (mask_type, seq_len, tile_q, tile_k, total_tile_pairs,
                actual_mask_calls, calls_saved)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (mask_name, T_test, tq_test, tk_test, total_pairs,
             call_count[0], total_pairs - call_count[0])
        )

    conn.commit()

    # Print summary
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM benchmark_runs")
    print(f"benchmark_runs: {cursor.fetchone()[0]} rows")
    cursor.execute("SELECT COUNT(*) FROM mask_call_counts")
    print(f"mask_call_counts: {cursor.fetchone()[0]} rows")
    cursor.execute(
        "SELECT mask_type, actual_mask_calls, calls_saved "
        "FROM mask_call_counts"
    )
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]} calls, {row[2]} saved")

    conn.close()
    print("benchmarks.db created successfully")


if __name__ == '__main__':
    main()
