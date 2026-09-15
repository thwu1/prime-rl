#!/usr/bin/env python3
"""Diagnostic sweep for the tiled attention engine.

Usage:
    python3 run_checks.py             # Run correctness checks
    python3 run_checks.py --profile   # Run with cProfile analysis
"""
import numpy as np
import cProfile
import sys

sys.path.insert(0, '/app')

from mask_base import FullMask
from masks import CausalMask, SlidingWindowMask, ChunkwiseMask, PrefixLMMask
from reference import naive_masked_attention

try:
    from engine import tiled_attention
    HAS_ENGINE = True
except (ImportError, NotImplementedError):
    HAS_ENGINE = False

try:
    from compound_masks import IntersectionMask, LocalGlobalMask
    HAS_COMPOUNDS = True
except (ImportError, NotImplementedError):
    HAS_COMPOUNDS = False

masks = [
    ("FullMask", FullMask()),
    ("CausalMask", CausalMask()),
    ("SlidingWindow(10,4)", SlidingWindowMask(10, 4)),
    ("SlidingWindow(2,0)", SlidingWindowMask(2, 0)),
    ("Chunkwise(8,2)", ChunkwiseMask(8, 2)),
    ("Chunkwise(4,0)", ChunkwiseMask(4, 0)),
    ("PrefixLM(10)", PrefixLMMask(10)),
    ("PrefixLM(3)", PrefixLMMask(3)),
]

if HAS_COMPOUNDS:
    masks.extend([
        ("Intersection(Causal,SW)", IntersectionMask(CausalMask(), SlidingWindowMask(10, 4))),
        ("LocalGlobal(5,3)", LocalGlobalMask(5, 3)),
    ])

configs = [
    (1, 1, 8, 8, 8, 8),
    (1, 1, 16, 8, 8, 8),
    (2, 2, 32, 16, 8, 8),
    (1, 1, 64, 8, 16, 16),
    (1, 1, 33, 8, 16, 16),
    (1, 1, 64, 8, 8, 32),
]


def run_sweep():
    if not HAS_ENGINE:
        print("ERROR: engine.py not implemented (tiled_attention raises NotImplementedError)")
        return False

    np.random.seed(42)
    results = []

    for mask_name, mask_obj in masks:
        for B, H, T, D, tq, tk in configs:
            q = np.random.randn(B, H, T, D).astype(np.float64)
            k_arr = np.random.randn(B, H, T, D).astype(np.float64)
            v = np.random.randn(B, H, T, D).astype(np.float64)

            ref_out, ref_lse = naive_masked_attention(q, k_arr, v, mask_obj)
            try:
                out, lse = tiled_attention(
                    q, k_arr, v, mask_obj, tile_q=tq, tile_k=tk
                )
                max_out_err = float(np.max(np.abs(out - ref_out)))
                valid = np.isfinite(ref_lse)
                max_lse_err = float(np.max(np.abs(
                    lse[valid] - ref_lse[valid]
                ))) if np.any(valid) else 0.0

                status = "PASS" if max_out_err <= 1e-10 else "FAIL"
                tag = f"B={B} H={H} T={T:3d} D={D:2d} tq={tq:2d} tk={tk:2d}"
                detail = f"out_err={max_out_err:.3e} lse_err={max_lse_err:.3e}"
                results.append((status, mask_name, tag, detail))
            except Exception as e:
                tag = f"B={B} H={H} T={T:3d} D={D:2d} tq={tq:2d} tk={tk:2d}"
                results.append(("ERROR", mask_name, tag, str(e)))

    print("=" * 80)
    print("DIAGNOSTIC SWEEP RESULTS")
    print("=" * 80)

    for status_filter in ["PASS", "FAIL", "ERROR"]:
        filtered = [r for r in results if r[0] == status_filter]
        if filtered:
            print(f"\n--- {status_filter} ({len(filtered)}) ---")
            for status, mask_name, tag, detail in filtered:
                print(f"  {mask_name:25s}  {tag}  {detail}")

    total = len(results)
    passed = sum(1 for r in results if r[0] == "PASS")
    failed = sum(1 for r in results if r[0] == "FAIL")
    errors = sum(1 for r in results if r[0] == "ERROR")
    print(f"\nSummary: {passed}/{total} passed, {failed} failed, {errors} errors")

    return failed + errors == 0


if __name__ == "__main__":
    if "--profile" in sys.argv:
        print("Running with cProfile...\n")
        profiler = cProfile.Profile()
        profiler.enable()
        success = run_sweep()
        profiler.disable()
        print("\n" + "=" * 80)
        print("PROFILE (top 30 by cumulative time)")
        print("=" * 80)
        profiler.print_stats(sort='cumulative')
    else:
        success = run_sweep()

    sys.exit(0 if success else 1)
