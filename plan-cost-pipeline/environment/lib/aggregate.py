#!/usr/bin/env python3
"""
Aggregate per-query evaluation results into a final report.

Reads per-query result JSON files and the combined q-errors file,
computes aggregate statistics, and writes the final report.
"""


import json
import os
import sys
import math


def percentile_linear(data, p):
    """Compute percentile using linear interpolation.

    Matches numpy's default 'linear' interpolation method.
    """
    n = len(data)
    if n == 0:
        return 0.0
    if n == 1:
        return data[0]
    k = (n - 1) * p / 100.0
    f = int(math.floor(k))
    c = min(int(math.ceil(k)), n - 1)
    if f == c:
        return data[f]
    return data[f] * (c - k) + data[c] * (k - f)


def main():
    if len(sys.argv) != 2:
        print("Usage: aggregate.py <output_dir>", file=sys.stderr)
        sys.exit(1)

    output_dir = sys.argv[1]

    # Read combined q-errors
    qerrors_file = os.path.join(output_dir, "all_qerrors.txt")
    with open(qerrors_file) as f:
        qerrors = sorted([float(line.strip()) for line in f if line.strip()])

    n = len(qerrors)
    if n == 0:
        print("ERROR: No q-errors collected", file=sys.stderr)
        sys.exit(1)

    # Read per-query plan costs from result files
    plan_costs = []
    for fname in sorted(os.listdir(output_dir)):
        if fname.endswith("_result.json"):
            filepath = os.path.join(output_dir, fname)
            with open(filepath) as f:
                result = json.load(f)
            plan_costs.append({
                "name": result["name"],
                "opt_cost": result["opt_cost"],
                "est_cost": result["est_cost"],
                "relative_cost": result["relative_cost"]
            })

    total_opt = sum(p["opt_cost"] for p in plan_costs)
    total_est = sum(p["est_cost"] for p in plan_costs)

    report = {
        "qerror_stats": {
            "count": n,
            "mean": round(sum(qerrors) / n, 6),
            "median": round(percentile_linear(qerrors, 50), 6),
            "p90": round(percentile_linear(qerrors, 90), 6),
            "p95": round(percentile_linear(qerrors, 95), 6),
            "p99": round(percentile_linear(qerrors, 99), 6)
        },
        "plan_costs": plan_costs,
        "total_opt_cost": round(total_opt, 6),
        "total_est_cost": round(total_est, 6),
        "total_relative_cost": round(total_est / total_opt, 6) if total_opt > 0 else None
    }

    report_file = os.path.join(output_dir, "report.json")
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to {}".format(report_file))


if __name__ == "__main__":
    main()
