#!/usr/bin/env python3
"""Generate synthetic daily maximum temperature data on a Gaussian N16 grid.

Creates a 10-year (2001-2010) dataset with:
- Latitude-dependent base temperature
- Seasonal cycle (reversed between hemispheres)
- Linear warming trend (0.3 K/year)
- AR(1)-correlated daily variability (rho=0.7, marginal std=2K)
"""


import numpy as np
from numpy.polynomial.legendre import leggauss
import netCDF4 as nc
from datetime import datetime, timedelta

# --- Grid: Gaussian N16 (32 latitudes, 64 longitudes) ---
N = 16
n_lats = 2 * N   # 32
n_lons = 2 * n_lats  # 64

# Gaussian latitudes from Legendre-Gauss quadrature
x_lg, _ = leggauss(n_lats)
lats = np.degrees(np.arcsin(x_lg[::-1]))  # North to South

# Evenly spaced longitudes
lons = np.arange(n_lons) * 360.0 / n_lons  # 0, 5.625, ..., 354.375

# --- Time axis: 2001-01-01 to 2010-12-31 ---
start = datetime(2001, 1, 1)
end = datetime(2010, 12, 31)
dates = []
d = start
while d <= end:
    dates.append(d)
    d += timedelta(days=1)
n_times = len(dates)  # 3652

time_vals = np.array([(d - start).days for d in dates], dtype=np.float64)
doys = np.array([d.timetuple().tm_yday for d in dates])
years = np.array([d.year for d in dates])

# --- AR(1) correlated noise ---
np.random.seed(42)
rho = 0.7
sigma = 2.0
sigma_e = sigma * np.sqrt(1.0 - rho ** 2)

white = np.random.normal(0, 1, size=(n_times, n_lats, n_lons)).astype(np.float32)
noise = np.zeros((n_times, n_lats, n_lons), dtype=np.float32)
noise[0] = white[0] * sigma
for t in range(1, n_times):
    noise[t] = rho * noise[t - 1] + sigma_e * white[t]

# --- Compute tasmax field ---
lat_rad = np.radians(lats)
cos_lat = np.cos(lat_rad)  # warm at equator
sin_lat = np.sin(lat_rad)  # sign flips across hemispheres

tasmax = np.zeros((n_times, n_lats, n_lons), dtype=np.float32)
for t in range(n_times):
    cos_doy = np.cos(2.0 * np.pi * doys[t] / 365.25)
    # Seasonal cycle: NH warm in Jul (cos_doy<0), cold in Jan (cos_doy>0)
    seasonal = -15.0 * cos_doy * sin_lat
    base = 273.15 + 25.0 * cos_lat + seasonal
    trend = 0.3 * (years[t] - 2001)
    tasmax[t, :, :] = base[:, np.newaxis] + trend + noise[t]

# --- Write NetCDF (classic format to avoid HDF5 attribute issues with CDO) ---
ds = nc.Dataset('/app/data/tasmax_daily_raw.nc', 'w', format='NETCDF3_CLASSIC')
ds.Conventions = 'CF-1.6'
ds.history = 'Synthetic benchmark data'

ds.createDimension('time', None)
ds.createDimension('lat', n_lats)
ds.createDimension('lon', n_lons)

tvar = ds.createVariable('time', 'f8', ('time',))
tvar.units = 'days since 2001-01-01 00:00:00'
tvar.calendar = 'standard'
tvar.axis = 'T'
tvar[:] = time_vals

latvar = ds.createVariable('lat', 'f8', ('lat',))
latvar.units = 'degrees_north'
latvar.long_name = 'latitude'
latvar.axis = 'Y'
latvar[:] = lats

lonvar = ds.createVariable('lon', 'f8', ('lon',))
lonvar.units = 'degrees_east'
lonvar.long_name = 'longitude'
lonvar.axis = 'X'
lonvar[:] = lons

tmax = ds.createVariable('tasmax', 'f4', ('time', 'lat', 'lon'))
tmax.units = 'K'
tmax.long_name = 'Daily Maximum Near-Surface Air Temperature'
tmax.standard_name = 'air_temperature'
tmax[:] = tasmax

ds.close()
print(f"Generated tasmax_daily_raw.nc: {n_times} timesteps, {n_lats}x{n_lons} grid")
