#!/usr/bin/env python3
"""COCO benchmarking analysis pipeline.

Processes optimization experiment data and computes standard COCO
performance metrics: ERT, ECDF, algorithm rankings, and scaling exponents.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loader import load_metadata, load_runs, get_runs  # noqa: E402
from ert import compute_ert  # noqa: E402
from ecdf import compute_ecdf  # noqa: E402
from rankings import compute_rankings  # noqa: E402
from scaling import compute_scaling  # noqa: E402

DATA_DIR = "/app/raw_data"
DB_PATH = "/app/benchmark.db"
BUDGETS = [100, 500, 1000, 5000, 10000, 50000, 100000, 500000]


def main():
    meta = load_metadata(DATA_DIR)
    all_runs = load_runs(DB_PATH, meta["algorithms"])

    print(f"Loaded data for {len(meta['algorithms'])} algorithms")
    for algo in meta["algorithms"]:
        print(f"  {algo}: {len(all_runs[algo])} runs")
    print(f"Functions: {meta['functions']}")
    print(f"Dimensions: {meta['dimensions']}")
    print()

    ert_results = compute_ert(
        all_runs, meta["algorithms"], meta["functions"],
        meta["dimensions"], meta["targets"], get_runs
    )
    print(f"Computed {len(ert_results)} ERT values")

    ecdf_results = compute_ecdf(
        all_runs, meta["algorithms"], meta["functions"],
        meta["dimensions"], meta["targets"], BUDGETS, get_runs
    )
    print(f"Computed {len(ecdf_results)} ECDF values")

    ranking_results = compute_rankings(
        ert_results, meta["algorithms"],
        meta["function_groups"], meta["dimensions"]
    )
    print(f"Computed rankings for {len(ranking_results)} function groups")

    scaling_results = compute_scaling(
        ert_results, meta["algorithms"],
        meta["functions"], meta["dimensions"]
    )
    print(f"Computed {len(scaling_results)} scaling exponents")

    output = {
        "ert": ert_results,
        "ecdf": ecdf_results,
        "rankings": ranking_results,
        "scaling_exponents": scaling_results,
    }

    with open("/app/output/report.json", "w") as f:
        json.dump(output, f, indent=2)

    print("\nPipeline complete. Results written to /app/output/report.json")


if __name__ == "__main__":
    os.makedirs("/app/output", exist_ok=True)
    main()
