#!/usr/bin/env python3
"""Generate synthetic raw observational NetCDF data for CMORization task.

Creates a deliberately non-CMOR-compliant NetCDF file with:
- Non-standard variable names (t2m, td2m, tp, sp) and orography (orog)
- Non-standard units (degC, mm/day, hPa)
- Longitude in -180..180 range
- Latitude in descending order
- Time in hours since 2000-01-01
- No coordinate bounds
- No scalar height coordinate
- float64 data (not float32)
- Quality control bit-flag variable
"""
import os
import sys
from datetime import datetime

import netCDF4 as nc
import numpy as np

os.makedirs("/app/raw_data", exist_ok=True)

# Grid parameters
NLAT = 36
NLON = 72
NTIME = 180  # 15 years x 12 months (Jan 2000 - Dec 2014)

# Coordinates (deliberately non-CMOR standard)
lat = np.linspace(87.5, -87.5, NLAT)     # DESCENDING order
lon = np.linspace(-177.5, 177.5, NLON)    # -180..180 range

# Time: hours since 2000-01-01 00:00:00 at noon on 15th of each month
base_date = datetime(2000, 1, 1)
time_vals = np.array([
    (datetime(2000 + t // 12, t % 12 + 1, 15, 12, 0, 0)
     - base_date).total_seconds() / 3600.0
    for t in range(NTIME)
], dtype=np.float64)

# Meshgrids for fully vectorized computation (no Python loops)
lat_grid, lon_grid = np.meshgrid(lat, lon, indexing='ij')  # (NLAT, NLON)
lat_rad = np.deg2rad(lat_grid)
lon_rad = np.deg2rad(lon_grid)

# ---- Surface elevation (orography) - static 2D field ----
dlat1, dlon1 = lat_grid - 30.0, lon_grid - 90.0
dlat2, dlon2 = lat_grid - 40.0, lon_grid + 110.0
dlat3, dlon3 = lat_grid + 15.0, lon_grid + 70.0

orog = (4000.0 * np.exp(-(dlat1**2 / 200.0 + dlon1**2 / 800.0))
        + 2500.0 * np.exp(-(dlat2**2 / 100.0 + dlon2**2 / 200.0))
        + 3000.0 * np.exp(-(dlat3**2 / 150.0 + dlon3**2 / 100.0))
        + 100.0 * (np.sin(lat_rad * 3) * np.cos(lon_rad * 4) + 1.0))
orog = np.maximum(orog, 0.0)

# Physical constants
g = 9.80665
Rd = 287.05

# ---- t2m: 2m temperature in degC (vectorized) ----
month_frac = (np.arange(NTIME) % 12) / 12.0                   # (NTIME,)
base_temp = 25.0 * np.cos(lat_rad) - 10.0                     # (NLAT, NLON)
seasonal = (15.0 * np.sin(lat_rad)[np.newaxis, :, :]
            * np.sin(2.0 * np.pi * month_frac)[:, np.newaxis, np.newaxis])
lapse = -6.5e-3 * orog                                        # (NLAT, NLON)
lonvar = 2.0 * np.cos(lon_rad * 2.0)                          # (NLAT, NLON)
t2m = (base_temp[np.newaxis, :, :] + seasonal
       + lapse[np.newaxis, :, :] + lonvar[np.newaxis, :, :])

# ---- td2m: 2m dewpoint temperature in degC (always <= t2m) ----
lat_dep = np.abs(lat_grid)
depression = (2.0 + 8.0 * np.exp(-((lat_dep - 25.0)**2) / 200.0)
              + 2.0 * np.abs(np.sin(lon_rad * 3.0)))
td2m = t2m - np.abs(depression)[np.newaxis, :, :]

# ---- tp: total precipitation in mm/day ----
tp_spatial = 5.0 * np.cos(lat_rad)**2 + 0.5 * np.sin(lon_rad * 3.0)
tp = np.maximum(0.0,
                tp_spatial[np.newaxis, :, :]
                + np.sin(2.0 * np.pi * month_frac)[:, np.newaxis, np.newaxis])

# ---- sp: surface pressure in hPa ----
T_kelvin = t2m + 273.15
sp = 1013.25 * np.exp(-g * orog[np.newaxis, :, :] / (Rd * T_kelvin))
sp = sp + 3.0 * np.sin(2.0 * np.pi * month_frac)[:, np.newaxis, np.newaxis]

# ---- qc_flag: quality control bit flags ----
np.random.seed(42)
b0 = (np.random.random((NTIME, NLAT, NLON)) < 0.03).astype(np.int32)
b1 = (np.random.random((NTIME, NLAT, NLON)) < 0.02).astype(np.int32) * 2
b2 = (np.random.random((NTIME, NLAT, NLON)) < 0.015).astype(np.int32) * 4
b3 = (np.random.random((NTIME, NLAT, NLON)) < 0.01).astype(np.int32) * 8
qc_flag = (b0 | b1 | b2 | b3).astype(np.int8)

# ---- Create NetCDF file ----
filepath = "/app/raw_data/SYNOBS_monthly_2000-2014.nc"
ds = nc.Dataset(filepath, "w", format="NETCDF4")

ds.createDimension("time", None)
ds.createDimension("latitude", NLAT)
ds.createDimension("longitude", NLON)

time_var = ds.createVariable("time", "f8", ("time",))
time_var.units = "hours since 2000-01-01 00:00:00"
time_var.calendar = "standard"
time_var.long_name = "time"
time_var[:] = time_vals
ds.sync()

lat_var = ds.createVariable("latitude", "f8", ("latitude",))
lat_var.units = "degrees_north"
lat_var.long_name = "Latitude"
lat_var[:] = lat
ds.sync()

lon_var = ds.createVariable("longitude", "f8", ("longitude",))
lon_var.units = "degrees_east"
lon_var.long_name = "Longitude"
lon_var[:] = lon
ds.sync()

v = ds.createVariable("t2m", "f8", ("time", "latitude", "longitude"),
                       fill_value=1e20)
v.units = "degC"
v.long_name = "2 metre temperature"
v.standard_name = "air_temperature"
v[:] = t2m
ds.sync()

v = ds.createVariable("td2m", "f8", ("time", "latitude", "longitude"),
                       fill_value=1e20)
v.units = "degC"
v.long_name = "2 metre dewpoint temperature"
v.standard_name = "dew_point_temperature"
v[:] = td2m
ds.sync()

v = ds.createVariable("tp", "f8", ("time", "latitude", "longitude"),
                       fill_value=1e20)
v.units = "mm/day"
v.long_name = "Total precipitation"
v.standard_name = "precipitation_flux"
v[:] = tp
ds.sync()

v = ds.createVariable("sp", "f8", ("time", "latitude", "longitude"),
                       fill_value=1e20)
v.units = "hPa"
v.long_name = "Surface pressure"
v.standard_name = "surface_air_pressure"
v[:] = sp
ds.sync()

v = ds.createVariable("orog", "f8", ("latitude", "longitude"))
v.units = "m"
v.long_name = "Surface altitude"
v.standard_name = "surface_altitude"
v[:] = orog
ds.sync()

v = ds.createVariable("qc_flag", "i1", ("time", "latitude", "longitude"))
v.long_name = "Quality control bit flags"
v.flag_masks = np.array([1, 2, 4, 8], dtype=np.int8)
v.flag_meanings = ("sensor_malfunction climatological_range_exceeded "
                   "spatial_consistency_failed temporal_consistency_failed")
v.valid_range = np.array([0, 15], dtype=np.int8)
v.comment = ("Bit field quality flags following CF conventions. "
             "Any non-zero value indicates the observation failed "
             "quality control and should be excluded from analysis.")
v[:] = qc_flag
ds.sync()

ds.Conventions = "CF-1.6"
ds.institution = "Synthetic Data Provider"
ds.title = "SYNOBS raw monthly data"
ds.source = "Generated synthetic data"

ds.close()

# ---- Verification: re-read and confirm all variables exist ----
print(f"Generated: {filepath}")
verify = nc.Dataset(filepath, "r")
expected = {"t2m", "td2m", "tp", "sp", "orog", "qc_flag",
            "time", "latitude", "longitude"}
actual = set(verify.variables.keys())
missing = expected - actual
if missing:
    print(f"FATAL: Missing variables in output: {missing}", file=sys.stderr)
    verify.close()
    sys.exit(1)
for vn in ["t2m", "td2m", "tp", "sp"]:
    s = verify.variables[vn].shape
    assert s == (NTIME, NLAT, NLON), f"{vn} shape {s} != expected"
assert verify.variables["orog"].shape == (NLAT, NLON)
assert verify.variables["qc_flag"].shape == (NTIME, NLAT, NLON)
verify.close()
print(f"  Dims: time={NTIME}, latitude={NLAT}, longitude={NLON}")
print(f"  Variables: t2m, td2m, tp, sp, orog, qc_flag")
print("  Verification passed: all variables present with correct shapes.")
