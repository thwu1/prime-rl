#!/usr/bin/env python3
"""
Hydrological Return Level Analysis Pipeline

Computes 100-year flood return levels for gauge stations using
L-moment-based GEV distribution fitting, with distribution selection
via L-moment ratio diagram analysis and bootstrap confidence intervals.
"""
import subprocess
import json
import os
import sys
import numpy as np

sys.path.insert(0, "/app")
from analysis.lmoments import sample_lmoments
from analysis.fit import fit_gev, return_level_gev
from analysis.distselect import select_distribution, bootstrap_return_level


def run_extraction(station_id):
    """Run the data extraction pipeline for a station."""
    result = subprocess.run(
        ["/app/pipeline/extract.sh", station_id],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Extraction failed for {station_id}: {result.stderr}"
        )

    values = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line:
            values.append(float(line))
    return np.array(values)


def analyze_station(station_id):
    """Extract data, fit GEV, select distribution, compute CIs."""
    x = run_extraction(station_id)
    if len(x) < 5:
        raise ValueError(
            f"Insufficient data for {station_id}: only {len(x)} values"
        )

    # Fit GEV and compute return level
    loc, scale, shape = fit_gev(x)
    rl100 = return_level_gev(loc, scale, shape, 100)

    # Distribution selection via L-moment ratio diagram
    dist_result = select_distribution(x)

    # Bootstrap confidence interval
    boot_result = bootstrap_return_level(x, T=100)

    return {
        "gev_loc": round(float(loc), 6),
        "gev_scale": round(float(scale), 6),
        "gev_shape": round(float(shape), 6),
        "return_level_100yr": round(float(rl100), 6),
        "n_samples": len(x),
        "distribution_selection": dist_result,
        "bootstrap_ci": boot_result,
    }


def main():
    with open("/app/data/stations.json") as f:
        config = json.load(f)

    results = {}
    for station in config["stations"]:
        sid = station["id"]
        print(f"Analyzing {sid} ({station['name']})...")
        try:
            results[sid] = analyze_station(sid)
            r = results[sid]
            print(f"  GEV(loc={r['gev_loc']:.2f}, "
                  f"scale={r['gev_scale']:.2f}, "
                  f"shape={r['gev_shape']:.4f})")
            print(f"  100-yr return level: {r['return_level_100yr']:.2f}")
            print(f"  n_samples: {r['n_samples']}")
            ds = r["distribution_selection"]
            print(f"  Best distribution: {ds['selected']} "
                  f"(tau3={ds['tau3']:.4f}, tau4={ds['tau4']:.4f})")
            bc = r["bootstrap_ci"]
            print(f"  Bootstrap 95% CI: [{bc['ci_lower']:.2f}, "
                  f"{bc['ci_upper']:.2f}]")
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            raise

    os.makedirs("/app/output", exist_ok=True)
    outpath = "/app/output/return_levels.json"
    with open(outpath, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {outpath}")


if __name__ == "__main__":
    main()
