#!/usr/bin/env python3
"""
SPH simulation quality assessment -- reference solution.

"""

import json
import math
import os
import sys
from pathlib import Path
from statistics import median
from xml.etree import ElementTree as ET


def parse_sphinxsys_xml(filepath):
    """Parse SPHinXsys XML regression data (attribute format)."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    snap_elem = root.find(".//Snapshot")
    n_snapshots = int(snap_elem.get("number_of_snapshot_for_local_result_"))

    particle = root.find(".//Particle_0")
    values = []
    for i in range(n_snapshots):
        val = float(particle.get("snapshot_{}".format(i)))
        values.append(val)

    return values


def dtw_sakoe_chiba(series_a, series_b, band_fraction=0.1):
    """Normalized DTW distance with Sakoe-Chiba band constraint."""
    n = len(series_a)
    m = len(series_b)
    w = max(1, math.ceil(band_fraction * max(n, m)))

    INF = float("inf")
    D = [[INF] * m for _ in range(n)]

    for i in range(n):
        for j in range(m):
            if abs(i - j) > w:
                continue

            cost = abs(series_a[i] - series_b[j])

            if i == 0 and j == 0:
                D[i][j] = cost
            elif i == 0:
                D[i][j] = cost + D[i][j - 1]
            elif j == 0:
                D[i][j] = cost + D[i - 1][j]
            else:
                D[i][j] = cost + min(D[i - 1][j], D[i][j - 1], D[i - 1][j - 1])

    return D[n - 1][m - 1] / (n + m)


def modified_z_scores(values):
    """Compute modified Z-scores using median absolute deviation."""
    med = median(values)
    abs_devs = [abs(v - med) for v in values]
    mad = median(abs_devs)

    scores = []
    for v in values:
        z = 0.6745 * (v - med) / (mad + 1e-10)
        scores.append(z)
    return scores


def richardson_extrapolation(f_fine, f_medium, f_coarse, r=2.0):
    """Estimate convergence order and extrapolated value."""
    num = abs(f_coarse - f_medium)
    den = abs(f_medium - f_fine)

    if den < 1e-15:
        return float("nan"), f_fine

    p = math.log(num / den) / math.log(r)
    f_exact = f_fine + (f_fine - f_medium) / (r ** p - 1)
    return p, f_exact


def main():
    data_dir = Path("/app/data")

    with open(data_dir / "config.json") as f:
        config = json.load(f)

    resolutions = config["resolutions"]
    quantities = config["quantities"]
    band_frac = config["band_fraction"]
    dist_thresh = config["distance_threshold"]
    conv_thresh_mean = config["convergence_threshold_mean"]
    conv_thresh_var = config["convergence_threshold_variance"]
    outlier_thresh = config["outlier_score_threshold"]
    r = config["refinement_ratio"]

    # -- Step 1: Parse all data ------------------------------------------------
    data = {}
    for res_name in resolutions:
        data[res_name] = {}
        for qty in quantities:
            qty_dir = data_dir / res_name / qty
            data[res_name][qty] = {
                "reference": parse_sphinxsys_xml(qty_dir / "reference.xml"),
                "runs": {},
            }
            for fpath in sorted(qty_dir.glob("run_*.xml")):
                run_name = fpath.stem
                data[res_name][qty]["runs"][run_name] = parse_sphinxsys_xml(fpath)

    # -- Step 2: Compute distances ---------------------------------------------
    similarity_analysis = {}
    dist_values = {}

    for res_name in resolutions:
        similarity_analysis[res_name] = {}
        dist_values[res_name] = {}
        for qty in quantities:
            similarity_analysis[res_name][qty] = {}
            dist_values[res_name][qty] = {}
            ref = data[res_name][qty]["reference"]
            for run_name in sorted(data[res_name][qty]["runs"]):
                run_data = data[res_name][qty]["runs"][run_name]
                d = dtw_sakoe_chiba(run_data, ref, band_frac)
                similarity_analysis[res_name][qty][run_name] = {
                    "distance": d,
                    "within_threshold": d < dist_thresh,
                }
                dist_values[res_name][qty][run_name] = d

    # -- Step 3: Outlier detection ---------------------------------------------
    outlier_detection = {}
    outlier_runs = set()

    for res_name in resolutions:
        outlier_detection[res_name] = {}
        for qty in quantities:
            outlier_detection[res_name][qty] = {}
            run_names = sorted(dist_values[res_name][qty])
            dist_vals = [dist_values[res_name][qty][rn] for rn in run_names]
            z_scores = modified_z_scores(dist_vals)

            for run_name, z in zip(run_names, z_scores):
                is_out = abs(z) > outlier_thresh
                outlier_detection[res_name][qty][run_name] = {
                    "outlier_score": z,
                    "is_outlier": is_out,
                }
                if is_out:
                    outlier_runs.add("{}/{}/{}".format(res_name, qty, run_name))

    # -- Step 4: Ensemble convergence (excluding outliers) ---------------------
    ensemble_convergence = {}
    ensemble_means_final = {}

    for res_name in resolutions:
        ensemble_convergence[res_name] = {}
        ensemble_means_final[res_name] = {}
        for qty in quantities:
            ref = data[res_name][qty]["reference"]
            n_snap = len(ref)

            # Filter runs
            clean_runs = []
            for run_name, run_data in data[res_name][qty]["runs"].items():
                key = "{}/{}/{}".format(res_name, qty, run_name)
                if key not in outlier_runs:
                    clean_runs.append(run_data)

            if not clean_runs:
                clean_runs = list(data[res_name][qty]["runs"].values())

            k = len(clean_runs)

            ens_mean = []
            ens_var = []
            for t in range(n_snap):
                vals = [run[t] for run in clean_runs]
                mu = sum(vals) / k
                var = sum((v - mu) ** 2 for v in vals) / k
                ens_mean.append(mu)
                ens_var.append(var)

            ensemble_means_final[res_name][qty] = ens_mean[-1]

            temp_mean_mean = sum(ens_mean) / n_snap
            temp_mean_var = sum(ens_var) / n_snap

            max_rel_mean = max(
                abs(ens_mean[t] - ref[t]) / (abs(ref[t]) + 1e-10)
                for t in range(n_snap)
            )
            max_rel_var = max(
                ens_var[t] / (abs(ref[t]) ** 2 + 1e-10)
                for t in range(n_snap)
            )

            ensemble_convergence[res_name][qty] = {
                "temporal_mean_of_ensemble_mean": temp_mean_mean,
                "temporal_mean_of_ensemble_variance": temp_mean_var,
                "mean_converged": max_rel_mean < conv_thresh_mean,
                "variance_converged": max_rel_var < conv_thresh_var,
            }

    # -- Step 5: Spatial convergence -------------------------------------------
    spatial_convergence = {}
    conv_orders = []

    for qty in quantities:
        f_fine = ensemble_means_final["fine"][qty]
        f_medium = ensemble_means_final["medium"][qty]
        f_coarse = ensemble_means_final["coarse"][qty]

        p, f_exact = richardson_extrapolation(f_fine, f_medium, f_coarse, r)

        spatial_convergence[qty] = {
            "convergence_order": p,
            "extrapolated_value": f_exact,
            "values_used": {
                "fine": f_fine,
                "medium": f_medium,
                "coarse": f_coarse,
            },
        }
        if not math.isnan(p):
            conv_orders.append(p)

    # -- Step 6: Overall assessment --------------------------------------------
    all_similarity_pass = all(
        similarity_analysis[res][qty][run]["within_threshold"]
        for res in similarity_analysis
        for qty in similarity_analysis[res]
        for run in similarity_analysis[res][qty]
    )

    all_converged = all(
        ensemble_convergence[res][qty]["mean_converged"]
        and ensemble_convergence[res][qty]["variance_converged"]
        for res in ensemble_convergence
        for qty in ensemble_convergence[res]
    )

    avg_order = (
        sum(conv_orders) / len(conv_orders) if conv_orders else float("nan")
    )

    output = {
        "similarity_analysis": similarity_analysis,
        "ensemble_convergence": ensemble_convergence,
        "spatial_convergence": spatial_convergence,
        "outlier_detection": outlier_detection,
        "overall_assessment": {
            "all_similarity_pass": all_similarity_pass,
            "all_converged": all_converged,
            "expected_convergence_order": avg_order,
            "outlier_runs": sorted(outlier_runs),
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
