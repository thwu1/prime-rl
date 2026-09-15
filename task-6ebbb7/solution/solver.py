"""
CFD Verification & Validation Post-Processing Pipeline
Computes:
1. Boundary layer integral parameters + Spalding law-of-wall fit
2. Richardson extrapolation & GCI for SA and SST turbulence models
3. Model-to-model comparison of grid-independent Cf values
"""

import json
import math
import csv
import os
from scipy.optimize import minimize_scalar
import numpy as np

DATA_ROOT = "/opt/cfd_data"


def load_config():
    with open(os.path.join(DATA_ROOT, "config.json")) as f:
        return json.load(f)


def load_bl_profile(filepath):
    """Load boundary layer velocity profile (y [m], U [m/s])"""
    y_vals = []
    u_vals = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    y_vals.append(float(parts[0]))
                    u_vals.append(float(parts[1]))
                except ValueError:
                    continue
    return np.array(y_vals), np.array(u_vals)


def load_cf_data(filepath):
    """Load CFD Cf data from CSV"""
    stations = []
    with open(filepath) as f:
        reader = csv.DictReader(
            (row for row in f if not row.strip().startswith("#"))
        )
        for row in reader:
            stations.append({
                "x": float(row["x"]),
                "grid1": float(row["Cf_grid1"]),
                "grid2": float(row["Cf_grid2"]),
                "grid3": float(row["Cf_grid3"]),
                "grid4": float(row["Cf_grid4"]),
            })
    return stations


def spalding_yplus(uplus, kappa, B):
    """Spalding's law of the wall: y+ as function of u+"""
    ku = kappa * uplus
    return uplus + math.exp(-kappa * B) * (
        math.exp(ku) - 1.0 - ku - ku**2 / 2.0 - ku**3 / 6.0
    )


def spalding_residual_sum(u_tau, y_data, U_data, nu, kappa, B):
    """Sum of squared residuals for Spalding fit"""
    total = 0.0
    for y, U in zip(y_data, U_data):
        yp_data = u_tau * y / nu
        up_data = U / u_tau
        yp_model = spalding_yplus(up_data, kappa, B)
        total += (yp_data - yp_model) ** 2
    return total


def compute_bl_analysis(config):
    """Compute boundary layer integral parameters and Spalding fit"""
    y, U = load_bl_profile(os.path.join(DATA_ROOT, "data/experimental/bl_profile.dat"))
    U_e = config["flow_conditions"]["U_e"]
    nu = config["flow_conditions"]["nu"]
    kappa = config["wall_model_constants"]["kappa"]
    B = config["wall_model_constants"]["B"]
    y_max_fit = config["spalding_fit"]["y_max_for_fit"]

    # Compute integral parameters using trapezoidal rule
    # Include contribution from wall (y=0, U=0) to first data point
    delta_star = 0.5 * ((1.0 - 0.0) + (1.0 - U[0] / U_e)) * y[0]
    theta = 0.5 * (0.0 + (U[0] / U_e) * (1.0 - U[0] / U_e)) * y[0]

    for i in range(1, len(y)):
        dy = y[i] - y[i - 1]
        f0_ds = 1.0 - U[i - 1] / U_e
        f1_ds = 1.0 - U[i] / U_e
        delta_star += 0.5 * (f0_ds + f1_ds) * dy

        f0_th = (U[i - 1] / U_e) * (1.0 - U[i - 1] / U_e)
        f1_th = (U[i] / U_e) * (1.0 - U[i] / U_e)
        theta += 0.5 * (f0_th + f1_th) * dy

    shape_factor = delta_star / theta

    # Spalding fit: find u_tau that minimizes residuals for inner-layer data
    mask = y <= y_max_fit
    y_fit = y[mask]
    U_fit = U[mask]

    result = minimize_scalar(
        spalding_residual_sum,
        bounds=(0.3, 2.0),
        method="bounded",
        args=(y_fit, U_fit, nu, kappa, B),
    )
    u_tau = result.x

    Cf = 2.0 * (u_tau / U_e) ** 2

    return {
        "delta_star": round(float(delta_star), 7),
        "theta": round(float(theta), 7),
        "shape_factor": round(float(shape_factor), 4),
        "u_tau": round(float(u_tau), 4),
        "Cf": round(float(Cf), 7),
    }


def richardson_extrapolation(f1, f2, f3, f4, r, Fs=1.25):
    """
    Richardson extrapolation using 3 finest grids + asymptotic range check with 4th.
    f1 = finest, f4 = coarsest.
    r = constant grid refinement ratio.
    """
    eps21 = f2 - f1
    eps32 = f3 - f2

    # Observed order of accuracy
    if eps21 == 0 or eps32 == 0:
        return None
    ratio = abs(eps32 / eps21)
    p = math.log(ratio) / math.log(r)

    # Extrapolated solution
    rp = r**p
    f_ext = f1 + (f1 - f2) / (rp - 1.0)

    # Approximate relative error (fine grid)
    e_a_21 = abs(eps21 / f1)

    # GCI fine
    gci_fine = Fs * e_a_21 / (rp - 1.0)

    # GCI medium (for asymptotic range check)
    e_a_32 = abs(eps32 / f2)
    gci_medium = Fs * e_a_32 / (rp - 1.0)

    # Asymptotic range indicator
    asymp_ratio = gci_medium / (rp * gci_fine)

    return {
        "p": round(p, 6),
        "f_ext": round(f_ext, 8),
        "gci_fine": round(gci_fine, 8),
        "gci_medium": round(gci_medium, 8),
        "asymp_ratio": round(asymp_ratio, 6),
    }


def compute_grid_convergence(cf_data, config):
    """Compute Richardson extrapolation and GCI for all stations"""
    r = config["grid_convergence"]["refinement_ratio"]
    Fs = config["grid_convergence"]["safety_factor"]

    stations = []
    for row in cf_data:
        result = richardson_extrapolation(
            row["grid1"], row["grid2"], row["grid3"], row["grid4"], r, Fs
        )
        if result is not None:
            result["x"] = row["x"]
            stations.append(result)

    return {"stations": stations}


def compute_model_comparison(sa_gc, sst_gc):
    """Compare extrapolated Cf values between SA and SST models"""
    stations_out = []
    diffs = []

    for sa_s, sst_s in zip(sa_gc["stations"], sst_gc["stations"]):
        sa_ext = sa_s["f_ext"]
        sst_ext = sst_s["f_ext"]
        diff = abs(sa_ext - sst_ext)
        rel = diff / max(abs(sa_ext), abs(sst_ext)) * 100.0
        diffs.append(rel)
        stations_out.append({
            "x": sa_s["x"],
            "sa_ext": sa_ext,
            "sst_ext": sst_ext,
            "rel_diff_pct": round(rel, 6),
        })

    rms = math.sqrt(sum(d**2 for d in diffs) / len(diffs))
    max_diff = max(diffs)
    max_idx = diffs.index(max_diff)

    return {
        "stations": stations_out,
        "rms_rel_diff_pct": round(rms, 6),
        "max_rel_diff_pct": round(max_diff, 6),
        "max_diff_station": stations_out[max_idx]["x"],
    }


def main():
    config = load_config()

    os.makedirs("/app/results", exist_ok=True)

    # 1. Boundary layer analysis
    bl_result = compute_bl_analysis(config)
    with open("/app/results/bl_analysis.json", "w") as f:
        json.dump(bl_result, f, indent=2)
    print(f"BL analysis: delta*={bl_result['delta_star']*1000:.3f} mm, "
          f"theta={bl_result['theta']*1000:.3f} mm, "
          f"H={bl_result['shape_factor']:.4f}, "
          f"u_tau={bl_result['u_tau']:.4f} m/s")

    # 2. Grid convergence - SA
    sa_data = load_cf_data(os.path.join(DATA_ROOT, "data/cfd/bump_cf_sa.csv"))
    sa_gc = compute_grid_convergence(sa_data, config)
    with open("/app/results/grid_convergence_sa.json", "w") as f:
        json.dump(sa_gc, f, indent=2)
    print(f"SA grid convergence: {len(sa_gc['stations'])} stations processed")

    # 3. Grid convergence - SST
    sst_data = load_cf_data(os.path.join(DATA_ROOT, "data/cfd/bump_cf_sst.csv"))
    sst_gc = compute_grid_convergence(sst_data, config)
    with open("/app/results/grid_convergence_sst.json", "w") as f:
        json.dump(sst_gc, f, indent=2)
    print(f"SST grid convergence: {len(sst_gc['stations'])} stations processed")

    # 4. Model comparison
    comparison = compute_model_comparison(sa_gc, sst_gc)
    with open("/app/results/model_comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)
    print(f"Model comparison: RMS diff={comparison['rms_rel_diff_pct']:.4f}%, "
          f"max diff={comparison['max_rel_diff_pct']:.4f}% at x={comparison['max_diff_station']}")


if __name__ == "__main__":
    main()
