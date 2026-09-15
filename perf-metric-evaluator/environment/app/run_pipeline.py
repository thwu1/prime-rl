#!/usr/bin/env python3
"""Entry point for the benchmark evaluation pipeline."""

from evaluator.pipeline import run_pipeline

if __name__ == "__main__":
    run_pipeline(
        "/opt/benchmark/data/benchmark_results.json",
        "/opt/benchmark/output/leaderboard.json",
    )
