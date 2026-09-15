#!/usr/bin/env python3
"""Radiotherapy dose analysis: DVH, dose summation, gamma, protocol compliance."""

import json
import math
import os

import numpy as np
from matplotlib.path import Path as MplPath
from scipy.ndimage import map_coordinates


def load_dose_grid(path):
    """Load dose grid from JSON, normalising to Gy."""
    with open(path) as f:
        data = json.load(f)
    dose = np.array(data["dose"], dtype=np.float64)
    unit = data.get("dose_unit", "Gy")
    if unit.lower() == "cgy":
        dose /= 100.0
    spacing = np.array(data["spacing"], dtype=np.float64)
    origin = np.array(data["origin"], dtype=np.float64)
    x = origin[0] + np.arange(data["nx"]) * spacing[0]
    y = origin[1] + np.arange(data["ny"]) * spacing[1]
    z = origin[2] + np.arange(data["nz"]) * spacing[2]
    return dose, (x, y, z), spacing


def get_structure_doses(dose, axes, spacing, contours):
    """Dose values for voxels inside a structure (XOR multi-contour per slice)."""
    x, y, z = axes
    all_doses = []
    for z_key, slice_contours in contours.items():
        z_val = float(z_key)
        z_idx = int(np.argmin(np.abs(z - z_val)))
        if abs(z[z_idx] - z_val) > spacing[2] / 2.0 + 0.01:
            continue
        xx, yy = np.meshgrid(x, y, indexing="ij")
        pts = np.column_stack([xx.ravel(), yy.ravel()])
        mask = np.zeros(len(pts), dtype=bool)
        for cd in slice_contours:
            poly = MplPath([(p[0], p[1]) for p in cd["data"]])
            mask = np.logical_xor(mask, poly.contains_points(pts))
        mask = mask.reshape(xx.shape)
        all_doses.extend(dose[:, :, z_idx][mask].tolist())
    return np.array(all_doses) if all_doses else np.array([])


def interp_onto(target_axes, source_dose, source_axes, source_spacing):
    """Resample source dose grid onto target coordinate system."""
    fi = (target_axes[0] - source_axes[0][0]) / source_spacing[0]
    fj = (target_axes[1] - source_axes[1][0]) / source_spacing[1]
    fk = (target_axes[2] - source_axes[2][0]) / source_spacing[2]
    FI, FJ, FK = np.meshgrid(fi, fj, fk, indexing="ij")
    coords = np.array([FI.ravel(), FJ.ravel(), FK.ravel()])
    interp = map_coordinates(source_dose, coords, order=1,
                             mode="constant", cval=0.0)
    return interp.reshape(len(target_axes[0]), len(target_axes[1]),
                          len(target_axes[2]))


def compute_gamma(ref_dose, ref_axes, eval_dose, eval_axes,
                  dose_pct, dist_mm, lower_pct, local=False):
    """3D gamma index — vectorised per reference point."""
    rx, ry, rz = ref_axes
    ex, ey, ez = eval_axes
    max_ref = float(np.max(ref_dose))
    lower_cutoff = lower_pct / 100.0 * max_ref
    dose_thresh = dose_pct / 100.0 * max_ref

    ri, rj, rk = np.where(ref_dose >= lower_cutoff)
    n_ref = len(ri)
    if n_ref == 0:
        return 100.0, 0, 0.0, 0.0

    EX, EY, EZ = np.meshgrid(ex, ey, ez, indexing="ij")
    ef_x, ef_y, ef_z = EX.ravel(), EY.ravel(), EZ.ravel()
    ed = eval_dose.ravel()

    gamma_mins = np.full(n_ref, np.inf)
    for idx in range(n_ref):
        px, py, pz = rx[ri[idx]], ry[rj[idx]], rz[rk[idx]]
        pd = ref_dose[ri[idx], rj[idx], rk[idx]]
        dists = np.sqrt((ef_x - px) ** 2 + (ef_y - py) ** 2 +
                        (ef_z - pz) ** 2)
        dd = ed - pd
        dt = (dose_pct / 100.0 * pd) if local else dose_thresh
        gamma = np.sqrt((dd / dt) ** 2 + (dists / dist_mm) ** 2)
        gamma_mins[idx] = np.min(gamma)

    pass_rate = float(np.sum(gamma_mins <= 1.0)) / n_ref * 100.0
    return pass_rate, n_ref, float(np.mean(gamma_mins)), float(np.max(gamma_mins))


def find_max_boost_factor(primary_dose, p_axes, p_spacing,
                          boost_dose, b_axes, b_spacing,
                          structures, constraints):
    """Largest non-negative scalar s keeping all OAR constraints satisfied."""
    boost_on_p = interp_onto(p_axes, boost_dose, b_axes, b_spacing)
    voxel_vol = float(np.prod(p_spacing)) / 1000.0
    max_s = float("inf")

    for sname, sdata in structures.items():
        if sdata.get("type") != "OAR" or sname not in constraints:
            continue
        p_d = get_structure_doses(primary_dose, p_axes, p_spacing,
                                  sdata["contours"])
        b_d = get_structure_doses(boost_on_p, p_axes, p_spacing,
                                  sdata["contours"])
        if len(p_d) == 0 or len(b_d) == 0:
            continue

        sc = constraints[sname]

        # Dmax: per-voxel analytical bound
        if "Dmax_gy_max" in sc:
            lim = sc["Dmax_gy_max"]
            for i in range(len(p_d)):
                if b_d[i] > 1e-10:
                    max_s = min(max_s, (lim - p_d[i]) / b_d[i])

        # Dmean: analytical
        if "Dmean_gy_max" in sc:
            lim = sc["Dmean_gy_max"]
            mb = float(np.mean(b_d))
            if mb > 1e-10:
                max_s = min(max_s, (lim - float(np.mean(p_d))) / mb)

        # V30: bisection
        if "V30_gy_pct_max" in sc:
            lim_pct = sc["V30_gy_pct_max"]
            v30_0 = float(np.sum(p_d >= 30.0)) / len(p_d) * 100.0
            if v30_0 > lim_pct:
                max_s = min(max_s, 0.0)
            else:
                lo, hi = 0.0, 1000.0
                for _ in range(100):
                    mid = (lo + hi) / 2
                    v30 = (float(np.sum(p_d + mid * b_d >= 30.0))
                           / len(p_d) * 100.0)
                    if v30 <= lim_pct:
                        lo = mid
                    else:
                        hi = mid
                max_s = min(max_s, lo)

        # D0.1cc: bisection
        if "D0_1cc_gy_max" in sc:
            lim = sc["D0_1cc_gy_max"]
            n_01cc = int(math.ceil(0.1 / voxel_vol))
            sorted_p = np.sort(p_d)
            d01_0 = float(sorted_p[0] if n_01cc >= len(sorted_p)
                          else sorted_p[-n_01cc])
            if d01_0 > lim:
                max_s = min(max_s, 0.0)
            else:
                lo, hi = 0.0, 1000.0
                for _ in range(100):
                    mid = (lo + hi) / 2
                    combined = np.sort(p_d + mid * b_d)
                    d01 = float(combined[0] if n_01cc >= len(combined)
                                else combined[-n_01cc])
                    if d01 <= lim:
                        lo = mid
                    else:
                        hi = mid
                max_s = min(max_s, lo)

    return max(0.0, max_s) if max_s != float("inf") else 0.0


def main():
    data_dir = "/app/data"
    results_dir = "/app/results"
    os.makedirs(results_dir, exist_ok=True)

    # Load grids
    d_p, ax_p, sp_p = load_dose_grid(f"{data_dir}/dose_primary.json")
    d_s, ax_s, sp_s = load_dose_grid(f"{data_dir}/dose_secondary.json")
    d_b, ax_b, sp_b = load_dose_grid(f"{data_dir}/dose_boost.json")

    with open(f"{data_dir}/structures.json") as f:
        structures = json.load(f)
    with open(f"{data_dir}/protocol.json") as f:
        protocol = json.load(f)

    voxel_vol = float(np.prod(sp_p)) / 1000.0
    constraints = protocol["constraints"]

    # ---- Structure metrics ----
    struct_results = {}
    struct_doses_cache = {}

    for sname, sdata in structures.items():
        doses = get_structure_doses(d_p, ax_p, sp_p, sdata["contours"])
        struct_doses_cache[sname] = doses
        if len(doses) == 0:
            continue
        volume = len(doses) * voxel_vol
        sorted_d = np.sort(doses)

        if sname == "PTV":
            struct_results[sname] = {
                "volume_cm3": volume,
                "D95_gy": float(np.percentile(sorted_d, 5)),
                "Dmean_gy": float(np.mean(doses)),
                "Dmax_gy": float(np.max(doses)),
            }
        elif sname == "Heart":
            struct_results[sname] = {
                "volume_cm3": volume,
                "Dmean_gy": float(np.mean(doses)),
                "Dmax_gy": float(np.max(doses)),
                "V30_gy_pct": float(np.sum(doses >= 30.0)) / len(doses) * 100.0,
            }
        elif sname == "SpinalCord":
            n_01cc = int(math.ceil(0.1 / voxel_vol))
            d01 = float(sorted_d[0] if n_01cc >= len(sorted_d)
                        else sorted_d[-n_01cc])
            struct_results[sname] = {
                "volume_cm3": volume,
                "Dmax_gy": float(np.max(doses)),
                "D0_1cc_gy": d01,
            }

    # ---- Dose summation ----
    interp_s = interp_onto(ax_p, d_s, ax_s, sp_s)
    summed = d_p + interp_s
    dose_sum = {
        "max_dose_gy": float(np.max(summed)),
        "mean_dose_gy": float(np.mean(summed)),
    }

    # ---- Gamma ----
    gc = protocol["gamma"]
    local = gc.get("normalization", "global") == "local"
    pr, n, mg, xg = compute_gamma(
        d_p, ax_p, d_s, ax_s,
        gc["dose_threshold_pct"], gc["distance_threshold_mm"],
        gc["lower_dose_cutoff_pct"], local)
    gamma_results = {
        "pass_rate_pct": pr,
        "mean_gamma": mg,
        "max_gamma": xg,
        "evaluated_points": n,
    }

    # ---- Protocol compliance ----
    compliance = {}
    ptv_d95 = struct_results["PTV"]["D95_gy"]
    compliance["PTV_D95"] = bool(ptv_d95 >= constraints["PTV"]["D95_gy_min"])

    heart_dm = struct_results["Heart"]["Dmean_gy"]
    compliance["Heart_Dmean"] = bool(heart_dm <= constraints["Heart"]["Dmean_gy_max"])

    heart_v30 = struct_results["Heart"]["V30_gy_pct"]
    compliance["Heart_V30"] = bool(heart_v30 <= constraints["Heart"]["V30_gy_pct_max"])

    cord_dmax = struct_results["SpinalCord"]["Dmax_gy"]
    compliance["SpinalCord_Dmax"] = bool(
        cord_dmax <= constraints["SpinalCord"]["Dmax_gy_max"])

    cord_d01 = struct_results["SpinalCord"]["D0_1cc_gy"]
    compliance["SpinalCord_D0_1cc"] = bool(
        cord_d01 <= constraints["SpinalCord"]["D0_1cc_gy_max"])

    compliance["overall_pass"] = all(
        v for k, v in compliance.items() if isinstance(v, bool))

    # Max boost factor
    mbf = find_max_boost_factor(
        d_p, ax_p, sp_p, d_b, ax_b, sp_b, structures, constraints)
    compliance["max_boost_factor"] = round(mbf, 6)

    # ---- Write ----
    results = {
        "structures": struct_results,
        "dose_summation": dose_sum,
        "gamma": gamma_results,
        "protocol_compliance": compliance,
    }
    output_path = f"{results_dir}/analysis.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Analysis complete. Results written to {output_path}")


if __name__ == "__main__":
    main()
