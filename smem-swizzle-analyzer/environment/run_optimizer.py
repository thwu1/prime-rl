#!/usr/bin/env python3
"""Run the shared memory layout optimizer on all kernel configurations.

Reads tiling configs from /app/kernel_configs.yaml, evaluates XOR-swizzle
and padding strategies, selects the optimal strategy per config, and writes
results to /app/optimal_layouts.json and /app/analysis_report.csv.
"""

import sys

from smem_optimizer.evaluator import (
    load_configs,
    evaluate_config,
    select_optimal,
    write_json_report,
    write_csv_report,
)


def main():
    configs = load_configs("/app/kernel_configs.yaml")

    results = []
    for config in configs:
        print(f"Evaluating {config['name']}...", end=" ")
        evaluation = evaluate_config(config)
        optimal = select_optimal(evaluation)
        result = {**evaluation, **optimal}
        results.append(result)
        print(
            f"baseline={result['baseline_conflicts']}, "
            f"swizzle={result['swizzle_conflicts']}(tc={result['swizzle_sizeof_tc']}), "
            f"padding={result['padding_conflicts']}(pad={result['padding_amount']}), "
            f"optimal={result['optimal_strategy']}({result['optimal_conflicts']})"
        )

    write_json_report(results, "/app/optimal_layouts.json")
    write_csv_report(results, "/app/analysis_report.csv")
    print(f"\nWrote {len(results)} results to optimal_layouts.json and analysis_report.csv")


if __name__ == "__main__":
    main()
