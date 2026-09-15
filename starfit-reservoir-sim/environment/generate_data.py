#!/usr/bin/env python3
"""Generate NetCDF input data for the reservoir simulation."""
import math
from datetime import date, timedelta

import netCDF4 as nc
import numpy as np

start_date = date(1995, 1, 1)
mean_flow = 15.0
n_days = 730

ds = nc.Dataset("/app/data/reservoir.nc", "w", format="NETCDF4")

ds.createDimension("time", n_days)

# Reservoir parameters as global attributes
ds.GRanD_CAP_MCM = 40.0
ds.Obs_MEANFLOW_CUMECS = 15.0
ds.initial_storage_MCM = 20.0
ds.NORhi_min = 50.0
ds.NORhi_max = 90.0
ds.NORhi_alpha = 5.0
ds.NORhi_beta = -10.0
ds.NORhi_mu = 70.0
ds.NORlo_min = 20.0
ds.NORlo_max = 60.0
ds.NORlo_alpha = -3.0
ds.NORlo_beta = 8.0
ds.NORlo_mu = 40.0
ds.Release_min = -0.5
ds.Release_max = 1.0
ds.Release_alpha1 = 0.1
ds.Release_alpha2 = -0.05
ds.Release_beta1 = 0.15
ds.Release_beta2 = 0.03
ds.Release_p1 = 0.2
ds.Release_p2 = 0.1
ds.Release_c = 0.0
ds.start_date = "1995-01-01"
ds.n_days = n_days

time_var = ds.createVariable("time", "i4", ("time",))
time_var.units = "days since 1995-01-01"
time_var.calendar = "standard"
time_var[:] = np.arange(n_days)

inflow_var = ds.createVariable("inflow_cms", "f8", ("time",))
inflow_var.units = "m3/s"
inflow_var.long_name = "Daily mean inflow rate"

inflows = []
for i in range(n_days):
    d = start_date + timedelta(days=i)
    doy = d.timetuple().tm_yday

    # Seasonal snowmelt-driven pattern: peak around day 150 (late May)
    seasonal = 0.28 + 3.0 * math.exp(-(doy - 150) ** 2 / (2.0 * 35 ** 2))

    # Deterministic sub-weekly and biweekly perturbation
    perturb = (
        0.12 * math.sin(2 * math.pi * i / 7.3)
        + 0.08 * math.cos(2 * math.pi * i / 13.1)
        + 0.05 * math.sin(2 * math.pi * i / 31.7)
    )

    q = mean_flow * (seasonal + perturb)
    q = max(q, 0.5)
    inflows.append(q)

inflow_var[:] = np.array(inflows)

ds.close()
print(f"Generated NetCDF input with {n_days} days of inflow data.")
