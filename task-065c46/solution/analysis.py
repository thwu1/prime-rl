#!/usr/bin/env python3
"""
Grid convergence verification assessment for CFD workshop data.

"""

import csv
import json
import math
import os
import sqlite3
import statistics

import h5py


def load_data():
    """Load coefficient data from HDF5 and grid metadata from SQLite."""
    data = {}

    with h5py.File("/app/data/workshop.h5", "r") as hf:
        force_cols = list(hf["meta"].attrs["force_columns"])
        level_names = list(hf["meta"].attrs["level_order"])

        for pid in hf["data"]:
            grp = hf["data"][pid]
            forces = grp["forces"][:]
            solver = grp.attrs["solver"]
            turb = grp.attrs["turbulence_model"]

            data[pid] = {"solver": solver, "turbulence_model": turb, "levels": {}}
            for i, level in enumerate(level_names):
                data[pid]["levels"][level] = {
                    force_cols[j]: float(forces[i, j])
                    for j in range(len(force_cols))
                }

    conn = sqlite3.connect("/app/data/grid_metadata.db")
    c = conn.cursor()
    c.execute("SELECT participant_id, grid_level, grid_nodes FROM grid_specs")
    for pid, level, nodes in c.fetchall():
        if pid in data and level in data[pid]["levels"]:
            data[pid]["levels"][level]["grid_nodes"] = nodes
    conn.close()

    return data


def classify_convergence(f3, f2, f1):
    """Classify convergence from three grid levels (coarsest to finest)."""
    eps32 = f3 - f2
    eps21 = f2 - f1

    if abs(eps21) < 1e-15 and abs(eps32) < 1e-15:
        return "monotonic"
    if abs(eps21) < 1e-15:
        return "monotonic"
    if abs(eps32) < 1e-15:
        return "divergent"

    ratio = eps32 / eps21
    if ratio < 0:
        return "oscillatory"
    elif ratio > 1:
        return "monotonic"
    else:
        return "divergent"


def richardson_extrapolation(f3, f2, f1, r):
    """Compute grid-independent estimate and observed order."""
    eps32 = f3 - f2
    eps21 = f2 - f1

    if abs(eps21) < 1e-15:
        return f1, float("nan")

    ratio = eps32 / eps21
    if ratio <= 0 or ratio <= 1:
        return float("nan"), float("nan")

    p = math.log(ratio) / math.log(r)
    if p <= 0:
        return float("nan"), float("nan")

    rp = r ** p
    f_ext = f1 + (f1 - f2) / (rp - 1)
    return f_ext, p


def compute_gci(f3, f2, f1, r, p, Fs=1.25):
    """Compute Grid Convergence Index and asymptotic range indicator."""
    rp = r ** p
    e_a_21 = (f2 - f1) / f1
    GCI_fine = Fs * abs(e_a_21) / (rp - 1)
    e_a_32 = (f3 - f2) / f2
    GCI_coarse = Fs * abs(e_a_32) / (rp - 1)
    if GCI_fine > 1e-15:
        asymptotic_ratio = GCI_coarse / (rp * GCI_fine)
    else:
        asymptotic_ratio = float("nan")
    return GCI_fine, GCI_coarse, asymptotic_ratio


def chauvenet_criterion(values):
    """Apply Chauvenet's criterion for outlier detection."""
    n = len(values)
    if n < 3:
        return {}
    mean = statistics.mean(values)
    std = statistics.stdev(values)
    if std < 1e-15:
        return {}
    threshold_prob = 1.0 / (2 * n)
    outliers = {}
    for i, v in enumerate(values):
        z = (v - mean) / std
        prob = math.erfc(abs(z) / math.sqrt(2))
        if prob < threshold_prob:
            outliers[i] = z
    return outliers


def modified_z_scores(values):
    """Compute modified Z-scores using median and MAD."""
    n = len(values)
    sorted_vals = sorted(values)
    if n % 2 == 1:
        median = sorted_vals[n // 2]
    else:
        median = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
    abs_devs = sorted(abs(v - median) for v in values)
    if n % 2 == 1:
        mad = abs_devs[n // 2]
    else:
        mad = (abs_devs[n // 2 - 1] + abs_devs[n // 2]) / 2
    if mad < 1e-15:
        return [0.0] * n
    return [0.6745 * (v - median) / mad for v in values]


def main():
    data = load_data()
    os.makedirs("/app/output", exist_ok=True)

    participants = sorted(data.keys())
    coefficients = ["CD", "CL", "CM"]

    richardson_results = {}
    convergence_class = {}

    for pid in participants:
        pdata = data[pid]["levels"]
        N_f = pdata["Fine"]["grid_nodes"]
        N_m = pdata["Medium"]["grid_nodes"]
        h_f = N_f ** (-1.0 / 3.0)
        h_m = N_m ** (-1.0 / 3.0)
        r = h_m / h_f

        result = {}
        conv = {}
        for coeff in coefficients:
            f3 = pdata["Coarse"][coeff]
            f2 = pdata["Medium"][coeff]
            f1 = pdata["Fine"][coeff]
            conv[coeff] = classify_convergence(f3, f2, f1)
            if conv[coeff] == "monotonic":
                f_ext, p = richardson_extrapolation(f3, f2, f1, r)
                result[coeff] = {"extrapolated": f_ext, "p": p}
            else:
                result[coeff] = {"extrapolated": float("nan"), "p": float("nan")}

        richardson_results[pid] = result
        convergence_class[pid] = conv

    with open("/app/output/continuum_estimates.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "participant_id",
            "CD_extrapolated", "CL_extrapolated", "CM_extrapolated",
            "p_CD", "p_CL", "p_CM",
        ])
        for pid in participants:
            r_data = richardson_results[pid]
            writer.writerow([
                pid,
                r_data["CD"]["extrapolated"],
                r_data["CL"]["extrapolated"],
                r_data["CM"]["extrapolated"],
                r_data["CD"]["p"],
                r_data["CL"]["p"],
                r_data["CM"]["p"],
            ])

    with open("/app/output/convergence_types.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "participant_id", "CD_convergence", "CL_convergence", "CM_convergence",
        ])
        for pid in participants:
            c = convergence_class[pid]
            writer.writerow([pid, c["CD"], c["CL"], c["CM"]])

    gci_results = {}
    for pid in participants:
        if convergence_class[pid]["CD"] != "monotonic":
            continue
        p_cd = richardson_results[pid]["CD"]["p"]
        if math.isnan(p_cd):
            continue
        pdata = data[pid]["levels"]
        f3 = pdata["Coarse"]["CD"]
        f2 = pdata["Medium"]["CD"]
        f1 = pdata["Fine"]["CD"]
        N_f = pdata["Fine"]["grid_nodes"]
        N_m = pdata["Medium"]["grid_nodes"]
        r = (N_m ** (-1.0 / 3.0)) / (N_f ** (-1.0 / 3.0))
        gci_fine, gci_coarse, asym_ratio = compute_gci(f3, f2, f1, r, p_cd)
        gci_results[pid] = {
            "GCI_fine_CD": gci_fine,
            "GCI_coarse_CD": gci_coarse,
            "asymptotic_ratio_CD": asym_ratio,
        }

    with open("/app/output/uncertainty_bounds.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "participant_id", "GCI_fine_CD", "GCI_coarse_CD", "asymptotic_ratio_CD",
        ])
        for pid in participants:
            if pid in gci_results:
                g = gci_results[pid]
                writer.writerow([
                    pid, g["GCI_fine_CD"], g["GCI_coarse_CD"], g["asymptotic_ratio_CD"],
                ])

    valid_pids = []
    valid_cd_ext = []
    for pid in participants:
        if convergence_class[pid]["CD"] == "monotonic":
            cd_ext = richardson_results[pid]["CD"]["extrapolated"]
            if not math.isnan(cd_ext):
                valid_pids.append(pid)
                valid_cd_ext.append(cd_ext * 1e4)

    chauv_outliers = chauvenet_criterion(valid_cd_ext)
    mod_z = modified_z_scores(valid_cd_ext)

    outliers_list = []
    outlier_pids = set()
    for i, pid in enumerate(valid_pids):
        is_chauv = i in chauv_outliers
        mz = mod_z[i]
        is_mod_z = abs(mz) > 3.5
        if is_chauv or is_mod_z:
            outliers_list.append({
                "participant_id": pid,
                "chauvenet_flag": is_chauv,
                "modified_z_score": round(mz, 4),
            })
            outlier_pids.add(pid)

    with open("/app/output/outliers.json", "w") as f:
        json.dump(outliers_list, f, indent=2)

    clean_cd_ext = [
        valid_cd_ext[i] for i, pid in enumerate(valid_pids)
        if pid not in outlier_pids
    ]

    n = len(clean_cd_ext)
    mean_cd = statistics.mean(clean_cd_ext)
    std_cd = statistics.stdev(clean_cd_ext)

    sorted_cd = sorted(clean_cd_ext)
    if n % 2 == 1:
        median_cd = sorted_cd[n // 2]
    else:
        median_cd = (sorted_cd[n // 2 - 1] + sorted_cd[n // 2]) / 2

    q1_idx = (n - 1) * 0.25
    q3_idx = (n - 1) * 0.75
    q1_lo = int(math.floor(q1_idx))
    q1_hi = min(q1_lo + 1, n - 1)
    q1 = sorted_cd[q1_lo] + (q1_idx - q1_lo) * (sorted_cd[q1_hi] - sorted_cd[q1_lo])
    q3_lo = int(math.floor(q3_idx))
    q3_hi = min(q3_lo + 1, n - 1)
    q3 = sorted_cd[q3_lo] + (q3_idx - q3_lo) * (sorted_cd[q3_hi] - sorted_cd[q3_lo])
    iqr = q3 - q1

    ensemble = {
        "mean": round(mean_cd, 4),
        "std": round(std_cd, 4),
        "median": round(median_cd, 4),
        "iqr": round(iqr, 4),
        "n_valid": n,
    }

    with open("/app/output/ensemble_statistics.json", "w") as f:
        json.dump(ensemble, f, indent=2)

    print(f"Analysis complete. {n} valid participants in ensemble.")


if __name__ == "__main__":
    main()
