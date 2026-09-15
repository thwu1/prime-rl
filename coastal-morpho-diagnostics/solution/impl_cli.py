"""
CLI entry point for coastal morphological diagnostics.

Usage:
    python3 /app/coastal_diag/cli.py --config /app/data/config.json --output /app/output/report.json
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

# Ensure the package is importable
sys.path.insert(0, "/app")

from coastal_diag.profiles import fall_velocity_vanrijn, dean_profile
from coastal_diag.spectra import jonswap_spectrum, directional_spreading
from coastal_diag.metrics import brier_skill_score, rmse, volume_change, mass_balance_check
from coastal_diag.verification import run_diagnostics


def read_profile_csv(path):
    """Read a two-column (x, z) CSV profile."""
    x, z = [], []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            x.append(float(row["x"]))
            z.append(float(row["z"]))
    return np.array(x), np.array(z)


def main():
    parser = argparse.ArgumentParser(description="Coastal morphological diagnostics")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--output", required=True, help="Path for output report JSON")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    # --- Read profile data ---------------------------------------------------
    x_pre, z_pre = read_profile_csv(cfg["files"]["pre_storm"])
    _, z_sim = read_profile_csv(cfg["files"]["post_storm_sim"])
    _, z_obs = read_profile_csv(cfg["files"]["post_storm_obs"])

    # --- Sediment / Dean profile ---------------------------------------------
    D50 = cfg["sediment"]["D50"]
    temp = cfg["sediment"]["temperature"]
    ws = fall_velocity_vanrijn(D50, temp)
    A = 0.51 * ws ** 0.44
    z_dean = dean_profile(x_pre, D50, temp)

    # --- JONSWAP spectrum ----------------------------------------------------
    Hm0 = cfg["waves"]["Hm0"]
    Tp = cfg["waves"]["Tp"]
    gamma = cfg["waves"]["gamma"]
    f = np.linspace(0.01, 1.0, 5000)
    S = jonswap_spectrum(f, Hm0, Tp, gamma)

    # Recheck Hm0 from spectral integral
    m0 = np.trapz(S, f)
    Hm0_check = 4.0 * np.sqrt(m0)

    # --- Metrics -------------------------------------------------------------
    dx = cfg["grid"]["dx"]
    dy = cfg["grid"].get("dy", 1.0)

    bss = brier_skill_score(z_sim, z_obs, z_pre)
    rmse_val = rmse(z_sim, z_obs)
    vol_change = volume_change(z_pre, z_sim, dx, dy)

    # --- Diagnostics ---------------------------------------------------------
    diag_config = {
        "z_pre": z_pre.tolist(),
        "z_sim": z_sim.tolist(),
        "z_obs": z_obs.tolist(),
        "dx": dx,
        "dy": dy,
        "mass_balance_threshold": cfg["verification"]["mass_balance_threshold"],
    }
    if "slope_locations" in cfg["verification"]:
        diag_config["slope_locations"] = cfg["verification"]["slope_locations"]
        diag_config["expected_slopes"] = cfg["verification"]["expected_slopes"]
        diag_config["slope_tolerance"] = cfg["verification"].get("slope_tolerance", 0.1)

    diagnostics = run_diagnostics(diag_config)

    # --- Assemble report -----------------------------------------------------
    report = {
        "fall_velocity": float(ws),
        "dean_parameter_A": float(A),
        "spectrum": {
            "peak_frequency": float(1.0 / Tp),
            "Hm0_check": float(Hm0_check),
        },
        "brier_skill_score": float(bss),
        "rmse": float(rmse_val),
        "volume_change": float(vol_change),
        "diagnostics": diagnostics,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
