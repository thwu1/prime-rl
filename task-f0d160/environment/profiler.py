#!/usr/bin/env python3
"""GPU Attention Kernel Performance Profiler"""
import json
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from roofline import RooflineModel
from attention import AttentionAnalyzer
from kv_cache import KVCacheEstimator


def load_hardware_config():
    """Load GPU hardware specifications from SQLite database."""
    conn = sqlite3.connect("/app/data/hardware.db")
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT peak_tflops, bandwidth_gb_s, memory_gb "
        "FROM gpu_specs WHERE name = ?",
        ("NVIDIA H100 SXM",)
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise RuntimeError("GPU 'NVIDIA H100 SXM' not found in hardware.db")
    return {
        "peak_tflops": row["peak_tflops"],
        "bandwidth_gb_s": row["bandwidth_gb_s"],
        "memory_gb": row["memory_gb"],
    }


def main():
    hw_config = load_hardware_config()

    with open("/app/data/scenarios.json") as f:
        scenarios = json.load(f)
    with open("/app/data/analysis.json") as f:
        analysis = json.load(f)

    roofline = RooflineModel(hw_config)
    analyzer = AttentionAnalyzer()
    cache_est = KVCacheEstimator()

    results = {"scenarios": {}}
    results["ridge_point"] = roofline.ridge_point()

    for name, scenario in scenarios.items():
        s_result = analyzer.analyze(scenario, roofline)
        s_result["kv_cache_bytes"] = cache_est.estimate(scenario)
        results["scenarios"][name] = s_result

    cp = analysis["critical_prefill"]
    results["critical_prefill_seq_len"] = analyzer.find_critical_prefill_length(
        cp, roofline
    )

    gs = analysis["group_size_sweep"]
    results["group_size_analysis"] = analyzer.group_size_sweep(gs, roofline)

    with open("/app/report.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
