#!/usr/bin/env python3
"""Combine STA results into final timing report."""
import json
import sys

orig_path = sys.argv[1]
opt_path = sys.argv[2]
sim_ok = sys.argv[3].lower() == "true"

with open(orig_path) as f:
    orig = json.load(f)

with open(opt_path) as f:
    opt = json.load(f)

# Max frequency based on original critical path
delay = orig["critical_path_delay_ns"]
setup = orig["setup_time_ns"]
max_freq = 1000.0 / (delay + setup) if (delay + setup) > 0 else 0

report = {
    "original": orig,
    "optimized": {
        "netlist_path": "/app/optimized_netlist.v",
        "total_cells": opt["total_cells"],
        "cell_counts": opt["cell_counts"],
        "total_area_um2": opt["total_area_um2"],
        "critical_path_delay_ns": opt["critical_path_delay_ns"],
        "meets_timing": opt["meets_timing"],
        "worst_slack_ns": opt["worst_slack_ns"],
    },
    "simulation_verified": sim_ok,
    "max_frequency_mhz": round(max_freq, 2),
}

with open("/app/timing_report.json", "w") as f:
    json.dump(report, f, indent=2)

print(json.dumps(report, indent=2))
