"""
Benchmark comparison engine stub.
Study the Zig source at /app/poop-src/main.zig for reference.
See /app/schema.json for the required output format.
See /app/db_schema.sql for the required SQLite schema.
Only standard library modules allowed for statistical computation.
"""


import json
import sys


def compare_benchmarks(baseline_path, candidate_path, output_path):
    """Compare two benchmark runs. Write JSON report and populate SQLite DB at /app/benchmark.db."""
    raise NotImplementedError("Implement the benchmark comparison engine")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python3 benchmark_compare.py <baseline.json> <candidate.json> <output.json>")
        sys.exit(1)
    compare_benchmarks(sys.argv[1], sys.argv[2], sys.argv[3])
