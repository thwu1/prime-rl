#!/usr/bin/env python3
"""Generate deterministic synthetic inflow timeseries for STARFIT simulation.

Produces a 730-day snowmelt-driven seasonal inflow pattern with deterministic
sub-weekly perturbations.  Average inflow approximately equals the mean flow
parameter (15 m^3/s) used in the STARFIT release calibration.
"""

import csv
import math
from datetime import date, timedelta

start_date = date(1995, 1, 1)
mean_flow = 15.0  # m^3/s
n_days = 730

rows = []
for i in range(n_days):
    d = start_date + timedelta(days=i)
    doy = d.timetuple().tm_yday

    # Seasonal snowmelt-driven pattern: peak around day 150 (late May)
    # Base 0.28 + amplitude 3.0 with sigma 35 gives annual average ~ 1.0
    seasonal = 0.28 + 3.0 * math.exp(-(doy - 150) ** 2 / (2.0 * 35 ** 2))

    # Deterministic sub-weekly and biweekly perturbation
    perturb = (
        0.12 * math.sin(2 * math.pi * i / 7.3)
        + 0.08 * math.cos(2 * math.pi * i / 13.1)
        + 0.05 * math.sin(2 * math.pi * i / 31.7)
    )

    inflow = mean_flow * (seasonal + perturb)
    inflow = max(inflow, 0.5)  # minimum base flow

    rows.append((d.isoformat(), f"{inflow:.6f}"))

with open("/app/data/inflows.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["date", "inflow_cms"])
    writer.writerows(rows)

print(f"Generated {n_days} days of inflow data.")
