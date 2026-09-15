#!/usr/bin/env python3
"""
Validate engine predictions against CRC Handbook reference data.

Reads reference_data.csv, computes activity coefficients using the engine,
and prints per-electrolyte RMSE.

"""

import csv
import math
import sys

sys.path.insert(0, "/app")
from electrolyte_engine import compute_activity_coefficient

ref_by_salt = {}
with open("/app/reference_data.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        salt = row["salt"]
        ref_by_salt.setdefault(salt, []).append(
            {
                "cation": row["cation"],
                "anion": row["anion"],
                "nu_cation": int(row["nu_cation"]),
                "nu_anion": int(row["nu_anion"]),
                "molality": float(row["molality"]),
                "gamma_exp": float(row["gamma_exp"]),
            }
        )

print(f"{'Salt':>10s}  {'N':>3s}  {'RMSE':>8s}  {'Max Rel Err':>12s}")
print("-" * 40)

for salt, points in sorted(ref_by_salt.items()):
    sq_errors = []
    max_rel_err = 0.0
    for pt in points:
        cation = pt["cation"]
        anion = pt["anion"]
        m = pt["molality"]
        nu_cat = pt["nu_cation"]
        nu_an = pt["nu_anion"]

        comp = {cation: m * nu_cat, anion: m * nu_an}
        gamma_pred = compute_activity_coefficient(comp, cation)
        gamma_exp = pt["gamma_exp"]

        sq_errors.append((gamma_pred - gamma_exp) ** 2)
        if gamma_exp > 0:
            rel_err = abs(gamma_pred - gamma_exp) / gamma_exp
            max_rel_err = max(max_rel_err, rel_err)

    rmse = math.sqrt(sum(sq_errors) / len(sq_errors))
    print(f"{salt:>10s}  {len(points):>3d}  {rmse:>8.4f}  {max_rel_err:>11.2%}")

print("\nValidation complete.")
