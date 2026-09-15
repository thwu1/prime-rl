#!/usr/bin/env python3
"""Generate NetCDF input for the 3-reservoir cascade simulation.

NOTE: This script deliberately stores some variables under non-standard
names to simulate an upstream pipeline with schema drift. The simulation
code in io_utils.py expects canonical names.
"""
import math
from datetime import date, timedelta

import netCDF4 as nc
import numpy as np

start_date = date(1995, 1, 1)
n_days = 730

ds = nc.Dataset("/app/data/cascade.nc", "w", format="NETCDF4")
ds.createDimension("time", n_days)
ds.createDimension("n_reservoirs", 3)
ds.createDimension("n_reaches", 2)

ds.start_date = "1995-01-01"
ds.n_days = n_days
ds.n_reservoirs = 3
ds.n_reaches = 2
# NOTE: demand_target_cms stored as variable, not global attribute
# ds.demand_target_cms = 20.0  -- upstream pipeline omitted this

time_var = ds.createVariable("time", "i4", ("time",))
time_var.units = "days since 1995-01-01"
time_var[:] = np.arange(n_days)

cap = ds.createVariable("GRanD_CAP_MCM", "f8", ("n_reservoirs",))
cap[:] = [60.0, 35.0, 25.0]

mean_flow = ds.createVariable("Obs_MEANFLOW_CUMECS", "f8", ("n_reservoirs",))
mean_flow[:] = [18.0, 22.0, 28.0]

# Stored with non-canonical name (init_storage_mcm instead of initial_storage_MCM)
init_storage = ds.createVariable("init_storage_mcm", "f8", ("n_reservoirs",))
init_storage[:] = [30.0, 17.5, 12.5]

for name, vals in [
    ("NORhi_mu", [72.0, 68.0, 65.0]),
    ("NORhi_alpha", [6.0, 4.0, 3.0]),
    ("NORhi_beta", [-8.0, -6.0, -5.0]),
    ("NORhi_min", [55.0, 50.0, 48.0]),
    ("NORhi_max", [92.0, 88.0, 85.0]),
    ("NORlo_mu", [38.0, 35.0, 32.0]),
    ("NORlo_alpha", [-4.0, -3.0, -2.0]),
    ("NORlo_beta", [6.0, 5.0, 4.0]),
    ("NORlo_min", [18.0, 15.0, 12.0]),
    ("NORlo_max", [58.0, 55.0, 52.0]),
]:
    v = ds.createVariable(name, "f8", ("n_reservoirs",))
    v[:] = vals

for name, vals in [
    ("Release_min", [-0.5, -0.4, -0.45]),
    ("Release_max", [1.2, 1.0, 0.9]),
    ("Release_alpha1", [0.08, 0.10, 0.12]),
    ("Release_alpha2", [-0.04, -0.05, -0.03]),
    ("Release_beta1", [0.12, 0.15, 0.10]),
    ("Release_beta2", [0.02, 0.03, 0.025]),
    ("Release_p1", [0.18, 0.20, 0.22]),
    ("Release_p2", [0.08, 0.10, 0.12]),
    ("Release_c", [0.0, 0.0, 0.0]),
]:
    v = ds.createVariable(name, "f8", ("n_reservoirs",))
    v[:] = vals

# Stored with non-canonical name (muskingum_K instead of reach_K_days)
reach_K = ds.createVariable("muskingum_K", "f8", ("n_reaches",))
reach_K[:] = [2.0, 1.5]
reach_K.long_name = "Muskingum travel time"
reach_K.units = "days"

# Stored with non-canonical name (muskingum_x instead of reach_x)
reach_x = ds.createVariable("muskingum_x", "f8", ("n_reaches",))
reach_x[:] = [0.2, 0.25]
reach_x.long_name = "Muskingum weighting factor"

# Demand target stored as scalar variable instead of global attribute
demand_var = ds.createVariable("downstream_demand_cms", "f8")
demand_var.long_name = "Downstream demand target"
demand_var.units = "m3/s"
demand_var[:] = 20.0

inflows = ds.createVariable("inflow_cms", "f8", ("n_reservoirs", "time"))
inflows.units = "m3/s"

base_flows = [18.0, 5.0, 7.0]
for r in range(3):
    data = []
    phase = r * 0.7
    for i in range(n_days):
        d = start_date + timedelta(days=i)
        doy = d.timetuple().tm_yday
        seasonal = 0.28 + 3.0 * math.exp(-(doy - 150) ** 2 / (2.0 * 35 ** 2))
        perturb = (
            0.12 * math.sin(2 * math.pi * i / 7.3 + phase)
            + 0.08 * math.cos(2 * math.pi * i / 13.1 + phase)
            + 0.05 * math.sin(2 * math.pi * i / 31.7 + phase)
        )
        q = base_flows[r] * (seasonal + perturb)
        q = max(q, 0.5)
        data.append(q)
    inflows[r, :] = np.array(data)

ds.close()
print(f"Generated cascade NetCDF: {n_days} days, 3 reservoirs, 2 reaches.")
