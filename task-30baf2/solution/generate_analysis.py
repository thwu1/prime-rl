#!/usr/bin/env python3
"""Generate performance analysis using cProfile and tracemalloc."""

import sys
sys.path.insert(0, '/app')

import json
import cProfile
import pstats
import tracemalloc
import io
import numpy as np

from mask_base import FullMask
from masks import CausalMask, SlidingWindowMask, ChunkwiseMask, PrefixLMMask
from engine import tiled_attention


def run_profiling():
    masks_to_test = {
        'FullMask': FullMask(),
        'CausalMask': CausalMask(),
        'SlidingWindowMask': SlidingWindowMask(10, 4),
        'ChunkwiseMask': ChunkwiseMask(8, 2),
        'PrefixLMMask': PrefixLMMask(10),
    }

    B, H, T, D = 1, 1, 64, 8
    tile_q, tile_k = 16, 16
    np.random.seed(42)
    q = np.random.randn(B, H, T, D)
    k = np.random.randn(B, H, T, D)
    v = np.random.randn(B, H, T, D)

    per_mask_stats = {}

    tracemalloc.start()

    for mask_name, mask_obj in masks_to_test.items():
        # Count mask calls via function wrapping
        call_count = [0]
        original_mask = mask_obj.mask

        def counting_mask(*args, _orig=original_mask, _cnt=call_count, **kw):
            _cnt[0] += 1
            return _orig(*args, **kw)

        mask_obj.mask = counting_mask

        # Profile with cProfile
        profiler = cProfile.Profile()
        profiler.enable()
        tiled_attention(q, k, v, mask_obj, tile_q=tile_q, tile_k=tile_k)
        profiler.disable()

        # Extract timing via pstats
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats('cumulative')
        total_time = stats.total_tt

        per_mask_stats[mask_name] = {
            'mask_calls': call_count[0],
            'time_sec': round(total_time, 6)
        }

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    analysis = {
        'engine_profiling': {
            'per_mask_stats': per_mask_stats,
            'total_calls': len(masks_to_test),
            'config': {
                'B': B, 'H': H, 'T': T, 'D': D,
                'tile_q': tile_q, 'tile_k': tile_k
            }
        },
        'memory_profiling': {
            'peak_memory_bytes': peak,
            'peak_memory_mb': round(peak / (1024 * 1024), 2)
        }
    }

    with open('/app/analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2)

    print("analysis.json written successfully")
    print(f"Peak memory: {peak / 1024 / 1024:.2f} MB")
    for name, s in per_mask_stats.items():
        print(f"  {name}: {s['mask_calls']} mask calls, {s['time_sec']:.4f}s")


if __name__ == '__main__':
    run_profiling()
