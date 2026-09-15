#!/usr/bin/env python3
"""Transfer analysis CLI — reads scenario TOML and OEM files."""
import json
import sys
import tomllib
import os
import numpy as np
from astro import coe2rv, propagate_cowell, lambert_solve, j2_perturbation, parse_oem


def main():
    scenario_path = sys.argv[1]
    scenario_dir = os.path.dirname(os.path.abspath(scenario_path))

    with open(scenario_path, "rb") as f:
        config = tomllib.load(f)

    mu = config["body"]["mu"]
    J2_val = config["body"]["J2"]
    R_body = config["body"]["R"]

    chaser = config["chaser"]
    a = chaser["a"]
    ecc = chaser["ecc"]
    inc = np.radians(chaser["inc_deg"])
    raan = np.radians(chaser["raan_deg"])
    argp = np.radians(chaser["argp_deg"])
    nu = np.radians(chaser["nu_deg"])
    p = a * (1 - ecc ** 2)

    r0, v0 = coe2rv(mu, p, ecc, inc, raan, argp, nu)

    # Parse target ephemeris from OEM file
    target_cfg = config["target"]
    oem_path = os.path.join(scenario_dir, target_cfg["ephemeris_file"])
    ephemeris = parse_oem(oem_path)
    epoch_idx = target_cfg["epoch_index"]
    target_entry = ephemeris[epoch_idx]
    r_target = np.array([target_entry["x"], target_entry["y"], target_entry["z"]])
    v_target = np.array([target_entry["vx"], target_entry["vy"], target_entry["vz"]])

    transfer = config["transfer"]
    use_j2 = transfer["use_j2"]
    dep_times = np.arange(
        transfer["departure_start_s"],
        transfer["departure_end_s"] + 1e-10,
        transfer["departure_step_s"],
    )
    tof_values = np.arange(
        transfer["tof_min_s"],
        transfer["tof_max_s"] + 1e-10,
        transfer["tof_step_s"],
    )

    def j2_pert(t, state, mu_val):
        if not use_j2:
            return np.zeros(3)
        return j2_perturbation(t, state, mu_val, J2_val, R_body)

    grid = []

    for dep_t in dep_times:
        if dep_t == 0:
            r_dep, v_dep = r0.copy(), v0.copy()
        else:
            r_dep, v_dep = propagate_cowell(
                mu, r0, v0, float(dep_t), perturbation=j2_pert, rtol=1e-10
            )

        for tof in tof_values:
            try:
                sols = lambert_solve(
                    mu, r_dep, r_target, float(tof), M=0, prograde=True
                )
                if not sols:
                    continue
                v1_l, v2_l = sols[0]
                dv_dep = np.linalg.norm(v1_l - v_dep)
                dv_arr = np.linalg.norm(v2_l - v_target)
                dv_total = dv_dep + dv_arr
                grid.append(
                    {
                        "dep_s": float(dep_t),
                        "tof_s": float(tof),
                        "dv_km_s": float(dv_total),
                    }
                )
            except (ValueError, RuntimeError):
                continue

    if grid:
        optimal = min(grid, key=lambda x: x["dv_km_s"])
    else:
        optimal = {"dep_s": 0, "tof_s": 0, "dv_km_s": float("inf")}

    results = {
        "grid": grid,
        "optimal": {
            "dep_s": optimal["dep_s"],
            "tof_s": optimal["tof_s"],
            "dv_km_s": optimal["dv_km_s"],
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
