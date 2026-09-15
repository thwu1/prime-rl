#!/usr/bin/env python3

"""
Performance profiling and benchmarking: baseline vs optimized generation.
Produces Chrome trace JSON files and a benchmark results summary.
"""

import json
import os
import sys

sys.path.insert(0, "/app")

import torch
import torch.profiler
import torch.utils.benchmark as benchmark

from model import LLMModel, MODEL_CONFIG, generate_simple
from kv_inference import generate_cached


def main():
    torch.manual_seed(42)
    model = LLMModel(MODEL_CONFIG)
    model.eval()

    # Prompt of 25 tokens, generate 35 tokens
    prompt = torch.tensor([[i % MODEL_CONFIG["vocab_size"] for i in range(25)]])
    max_new = 35

    os.makedirs("/app/traces", exist_ok=True)

    # --- Chrome trace profiling ---
    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU],
        record_shapes=True,
    ) as prof_baseline:
        generate_simple(model, prompt.clone(), max_new)
    prof_baseline.export_chrome_trace("/app/traces/baseline.json")

    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU],
        record_shapes=True,
    ) as prof_optimized:
        generate_cached(model, prompt.clone(), max_new)
    prof_optimized.export_chrome_trace("/app/traces/optimized.json")

    # --- Benchmark timing with torch.utils.benchmark ---
    num_runs = 5

    baseline_timer = benchmark.Timer(
        stmt="generate_simple(model, prompt.clone(), max_new)",
        globals={
            "generate_simple": generate_simple,
            "model": model,
            "prompt": prompt,
            "max_new": max_new,
        },
    )

    optimized_timer = benchmark.Timer(
        stmt="generate_cached(model, prompt.clone(), max_new)",
        globals={
            "generate_cached": generate_cached,
            "model": model,
            "prompt": prompt,
            "max_new": max_new,
        },
    )

    baseline_measurement = baseline_timer.timeit(num_runs)
    optimized_measurement = optimized_timer.timeit(num_runs)

    baseline_ms = baseline_measurement.mean * 1000
    optimized_ms = optimized_measurement.mean * 1000
    speedup = baseline_ms / optimized_ms if optimized_ms > 0 else float("inf")

    results = {
        "baseline_mean_ms": round(baseline_ms, 3),
        "optimized_mean_ms": round(optimized_ms, 3),
        "speedup_ratio": round(speedup, 3),
    }

    with open("/app/benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Baseline:  {baseline_ms:.2f} ms")
    print(f"Optimized: {optimized_ms:.2f} ms")
    print(f"Speedup:   {speedup:.2f}x")


if __name__ == "__main__":
    main()
