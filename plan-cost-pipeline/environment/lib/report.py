#!/usr/bin/env python3
"""Combine plan costs and Q-Error statistics into final report."""


import json
import os
import sys


def main():
    if len(sys.argv) != 3:
        print("Usage: report.py <work_dir> <output.json>", file=sys.stderr)
        sys.exit(1)

    work_dir = sys.argv[1]
    output_file = sys.argv[2]

    # Read Q-Error statistics from awk output
    stats_file = os.path.join(work_dir, "qerror_stats.json")
    with open(stats_file) as f:
        qerror_stats = json.load(f)

    # Read per-query plan costs
    plan_costs = []
    for fname in sorted(os.listdir(work_dir)):
        if fname.endswith("_plan.json"):
            with open(os.path.join(work_dir, fname)) as f:
                plan = json.load(f)
            plan_costs.append({
                "name": plan["name"],
                "opt_cost": plan["opt_cost"],
                "est_cost": plan["est_cost"],
                "relative_cost": plan["relative_cost"],
            })

    plan_costs.sort(key=lambda x: x["name"])

    total_opt = sum(p["opt_cost"] for p in plan_costs)
    total_est = sum(p["est_cost"] for p in plan_costs)

    report = {
        "qerror_stats": qerror_stats,
        "plan_costs": plan_costs,
        "total_opt_cost": round(total_opt, 6),
        "total_est_cost": round(total_est, 6),
        "total_relative_cost": round(total_est / total_opt, 6) if total_opt > 0 else None,
    }

    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to {}".format(output_file))


if __name__ == "__main__":
    main()
