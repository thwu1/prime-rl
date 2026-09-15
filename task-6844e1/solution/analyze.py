#!/usr/bin/env python3
"""
Analyze simulation results and produce analysis.json.
"""


import json
import math
import os


def analyze():
    results_path = "/app/results/simulation.json"
    with open(results_path) as f:
        history = json.load(f)

    setpoint = history[0]["setpoint"]

    # Compute metrics over last 100 ticks
    last_100 = history[-100:]
    dirty_values = [h["nr_dirty"] for h in last_100]
    avg_dirty = sum(dirty_values) / len(dirty_values)

    mean = avg_dirty
    variance = sum((v - mean) ** 2 for v in dirty_values) / len(dirty_values)
    std_dev = math.sqrt(variance)
    cv_pct = (std_dev / mean) * 100 if mean > 0 else 0.0

    # BDI ratio
    avg_ssd = sum(h["bdi"]["ssd"]["dirty"] for h in last_100) / len(last_100)
    avg_hdd = sum(h["bdi"]["hdd"]["dirty"] for h in last_100) / len(last_100)
    bdi_ratio = avg_ssd / avg_hdd if avg_hdd > 0 else 0.0

    # Convergence check
    deviation = abs(avg_dirty - setpoint) / setpoint
    converged = deviation < 0.10 and cv_pct < 15.0

    analysis = {
        "converged": converged,
        "avg_dirty": round(avg_dirty, 2),
        "setpoint": setpoint,
        "cv_pct": round(cv_pct, 2),
        "bdi_ratio": round(bdi_ratio, 2),
    }

    analysis_path = "/app/results/analysis.json"
    with open(analysis_path, "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"Analysis written to {analysis_path}")
    print(json.dumps(analysis, indent=2))


if __name__ == "__main__":
    analyze()
