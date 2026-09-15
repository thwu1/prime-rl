#!/usr/bin/env python3
"""Generate deterministic synthetic daily inflows for two reservoirs."""
import csv
import math
import os


def generate_inflows():
    os.makedirs("/app/data", exist_ok=True)
    rows = []
    for d in range(730):
        # Reservoir 1: seasonal snowmelt-driven hydrograph
        q1 = (
            50.0
            + 30.0 * math.sin(2.0 * math.pi * d / 365.0 - math.pi / 2.0)
            + 10.0 * math.sin(2.0 * math.pi * d / 183.0)
        )
        q1 = max(5.0, q1)

        # Reservoir 2 local tributary: different phase and amplitude
        q2 = (
            20.0
            + 12.0 * math.sin(2.0 * math.pi * d / 365.0 - math.pi / 3.0)
            + 5.0 * math.sin(2.0 * math.pi * d / 91.25)
        )
        q2 = max(2.0, q2)

        rows.append((d, round(q1, 6), round(q2, 6)))

    with open("/app/data/inflows.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["day", "res1_inflow_cms", "res2_local_inflow_cms"])
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    generate_inflows()
    print("Generated /app/data/inflows.csv (730 rows)")
