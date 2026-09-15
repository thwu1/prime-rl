#!/usr/bin/env python3
"""Main entry point for the Flink streaming join optimizer."""

import json
import sys

from optimizer.parser import load_all_plans
from optimizer.report import generate_full_report, write_report


def main():
    config_path = "/app/config.json"
    with open(config_path, "r") as f:
        config = json.load(f)

    plans_dir = config.get("plans_dir", "/app/plans")
    output_dir = config.get("output_dir", "/app/output")
    safety_factor = config.get("safety_factor", 1.2)

    plans = load_all_plans(plans_dir)
    print(f"Loaded {len(plans)} execution plans")

    report = generate_full_report(plans, safety_factor=safety_factor)

    output_path = f"{output_dir}/report.json"
    write_report(report, output_path)
    print(f"Report written to {output_path}")


if __name__ == "__main__":
    main()
