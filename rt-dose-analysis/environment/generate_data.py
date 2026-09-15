#!/usr/bin/env python3
"""Generate synthetic radiotherapy dose grid and structure contour data.

Creates deterministic 3D dose distributions, multi-structure contours with
holes, and a clinical protocol. All output is JSON, stdlib-only.
"""

import json
import math
import os


def _gauss(x, y, z, peak, sigma, cx=0.0, cy=0.0, cz=0.0):
    r2 = (x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2
    return round(peak * math.exp(-r2 / (2.0 * sigma * sigma)), 10)


def generate(output_dir="/app/data"):
    os.makedirs(output_dir, exist_ok=True)

    # ---- Primary dose grid (Gy) ----
    p_nx, p_ny, p_nz = 20, 20, 12
    p_sp = [2.5, 2.5, 3.0]
    p_or = [-23.75, -23.75, -16.5]
    p_x = [p_or[0] + i * p_sp[0] for i in range(p_nx)]
    p_y = [p_or[1] + j * p_sp[1] for j in range(p_ny)]
    p_z = [p_or[2] + k * p_sp[2] for k in range(p_nz)]

    sigma_p = 18.0
    p_dose = [[[_gauss(p_x[i], p_y[j], p_z[k], 60.0, sigma_p)
                for k in range(p_nz)]
               for j in range(p_ny)]
              for i in range(p_nx)]

    with open(os.path.join(output_dir, "dose_primary.json"), "w") as f:
        json.dump({"nx": p_nx, "ny": p_ny, "nz": p_nz,
                    "spacing": p_sp, "origin": p_or,
                    "dose_unit": "Gy", "dose": p_dose}, f)

    # ---- Secondary dose grid (stored in cGy) ----
    s_nx, s_ny, s_nz = 18, 18, 10
    s_sp = [3.0, 3.0, 3.5]
    s_or = [-25.5, -25.5, -15.75]
    s_x = [s_or[0] + i * s_sp[0] for i in range(s_nx)]
    s_y = [s_or[1] + j * s_sp[1] for j in range(s_ny)]
    s_z = [s_or[2] + k * s_sp[2] for k in range(s_nz)]

    sigma_s = 18.0
    s_dose = [[[_gauss(s_x[i], s_y[j], s_z[k], 5800.0, sigma_s, 2.0, -1.5, 0.8)
                for k in range(s_nz)]
               for j in range(s_ny)]
              for i in range(s_nx)]

    with open(os.path.join(output_dir, "dose_secondary.json"), "w") as f:
        json.dump({"nx": s_nx, "ny": s_ny, "nz": s_nz,
                    "spacing": s_sp, "origin": s_or,
                    "dose_unit": "cGy", "dose": s_dose}, f)

    # ---- Boost dose grid (Gy, tighter, covers full anatomy) ----
    b_nx, b_ny, b_nz = 16, 16, 10
    b_sp = [3.5, 3.5, 4.0]
    b_or = [-26.25, -26.25, -18.0]
    b_x = [b_or[0] + i * b_sp[0] for i in range(b_nx)]
    b_y = [b_or[1] + j * b_sp[1] for j in range(b_ny)]
    b_z = [b_or[2] + k * b_sp[2] for k in range(b_nz)]

    sigma_b = 10.0
    b_dose = [[[_gauss(b_x[i], b_y[j], b_z[k], 12.0, sigma_b)
                for k in range(b_nz)]
               for j in range(b_ny)]
              for i in range(b_nx)]

    with open(os.path.join(output_dir, "dose_boost.json"), "w") as f:
        json.dump({"nx": b_nx, "ny": b_ny, "nz": b_nz,
                    "spacing": b_sp, "origin": b_or,
                    "dose_unit": "Gy", "dose": b_dose}, f)

    # ---- Structures ----
    n_pts = 48
    structures = {}

    # PTV: sphere r=10 mm at origin, with inner exclusion r=4 mm near z=0
    ptv_contours = {}
    ptv_r = 10.0
    hole_r = 4.0
    for k in range(p_nz):
        zv = p_z[k]
        if abs(zv) < ptv_r:
            rz = math.sqrt(ptv_r ** 2 - zv ** 2)
            outer = [[round(rz * math.cos(2 * math.pi * p / n_pts), 8),
                       round(rz * math.sin(2 * math.pi * p / n_pts), 8),
                       round(zv, 8)] for p in range(n_pts)]
            sc = [{"data": outer}]
            if abs(zv) < hole_r:
                rh = math.sqrt(hole_r ** 2 - zv ** 2)
                inner = [[round(rh * math.cos(2 * math.pi * p / n_pts), 8),
                           round(rh * math.sin(2 * math.pi * p / n_pts), 8),
                           round(zv, 8)] for p in range(n_pts)]
                sc.append({"data": inner})
            ptv_contours[str(round(zv, 1))] = sc
    structures["PTV"] = {"name": "PTV", "type": "TARGET", "contours": ptv_contours}

    # Heart: ellipsoid centred at (18, 14, 0), semi-axes (7, 9, 8)
    h_cx, h_cy, h_cz = 18.0, 14.0, 0.0
    h_a, h_b, h_c = 7.0, 9.0, 8.0
    heart_contours = {}
    for k in range(p_nz):
        zv = p_z[k]
        dz = (zv - h_cz) / h_c
        if abs(dz) < 1.0:
            sc = math.sqrt(1.0 - dz ** 2)
            pts = [[round(h_cx + h_a * sc * math.cos(2 * math.pi * p / n_pts), 8),
                    round(h_cy + h_b * sc * math.sin(2 * math.pi * p / n_pts), 8),
                    round(zv, 8)] for p in range(n_pts)]
            heart_contours[str(round(zv, 1))] = [{"data": pts}]
    structures["Heart"] = {"name": "Heart", "type": "OAR", "contours": heart_contours}

    # Spinal cord: cylinder at (-20, 0), radius 3.5 mm, all z-slices
    c_cx, c_cy = -20.0, 0.0
    c_r = 3.5
    n_c = 32
    cord_contours = {}
    for k in range(p_nz):
        zv = p_z[k]
        pts = [[round(c_cx + c_r * math.cos(2 * math.pi * p / n_c), 8),
                round(c_cy + c_r * math.sin(2 * math.pi * p / n_c), 8),
                round(zv, 8)] for p in range(n_c)]
        cord_contours[str(round(zv, 1))] = [{"data": pts}]
    structures["SpinalCord"] = {"name": "SpinalCord", "type": "OAR",
                                 "contours": cord_contours}

    with open(os.path.join(output_dir, "structures.json"), "w") as f:
        json.dump(structures, f)

    # ---- Clinical protocol ----
    protocol = {
        "constraints": {
            "PTV": {"D95_gy_min": 40.0},
            "Heart": {"Dmean_gy_max": 30.0, "V30_gy_pct_max": 50.0},
            "SpinalCord": {"Dmax_gy_max": 50.0, "D0_1cc_gy_max": 45.0}
        },
        "gamma": {
            "dose_threshold_pct": 3.0,
            "distance_threshold_mm": 3.0,
            "lower_dose_cutoff_pct": 10.0,
            "normalization": "global"
        }
    }
    with open(os.path.join(output_dir, "protocol.json"), "w") as f:
        json.dump(protocol, f, indent=2)

    print(f"Data generated in {output_dir}")


if __name__ == "__main__":
    generate()
