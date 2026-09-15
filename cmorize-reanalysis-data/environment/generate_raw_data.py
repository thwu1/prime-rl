#!/usr/bin/env python3
"""Generate synthetic raw climate data for CMORization task."""
import numpy as np
import netCDF4 as nc
import os
import calendar
from datetime import datetime, timedelta

np.random.seed(42)

nlat = 73
nlon = 144
ntime = 36

# Latitude: 90 to -90 descending (non-standard, needs flipping)
lat = np.linspace(90, -90, nlat)

# Longitude: -180 to 177.5 (non-standard, needs wrapping to 0-360)
lon = np.linspace(-180, 177.5, nlon)

# Time: hours since 1900-01-01, at month start (1st of each month)
base_date = datetime(1900, 1, 1)
time_vals = []
month_secs = []
for year in range(2000, 2003):
    for month in range(1, 13):
        dt = datetime(year, month, 1)
        hours = (dt - base_date).total_seconds() / 3600.0
        time_vals.append(hours)
        days_in_month = calendar.monthrange(year, month)[1]
        month_secs.append(days_in_month * 86400.0)

time_vals = np.array(time_vals)
month_secs = np.array(month_secs)
lat_rad = np.radians(lat)
lon_rad = np.radians(lon)

# Orography difference field (z_model - z_true) in meters
# Varies spatially with realistic patterns
orog_diff = np.zeros((nlat, nlon), dtype=np.float64)
for i in range(nlat):
    for j in range(nlon):
        orog_diff[i, j] = (
            100 * np.sin(lat_rad[i] * 3) * np.cos(lon_rad[j] * 2) +
            60 * np.sin(lon_rad[j] * 5) +
            40 * np.cos(lat_rad[i] * 7 + lon_rad[j] * 3)
        )

# Lapse rate correction embedded in t2m: delta_T = 0.0065 * orog_diff (K)
lapse_correction = 0.0065 * orog_diff

# t2m: 2-metre temperature in K
# Has: (1) +0.5K constant warm bias, (2) orographic representativeness error
t2m = np.zeros((ntime, nlat, nlon), dtype=np.float64)
for t in range(ntime):
    month = t % 12
    base_temp = 275 + 25 * np.cos(lat_rad)
    seasonal = 10 * np.sin(2 * np.pi * (month - 3) / 12.0) * np.sin(lat_rad)
    noise = np.random.normal(0, 1.5, (nlat, nlon))
    true_temp = base_temp[:, np.newaxis] + seasonal[:, np.newaxis] + noise
    # Embed constant bias and orographic error
    t2m[t] = true_temp + 0.5 - lapse_correction

# d2m: 2-metre dewpoint temperature in K (no data quality issues)
d2m = np.zeros((ntime, nlat, nlon), dtype=np.float64)
for t in range(ntime):
    true_temp = t2m[t] - 0.5 + lapse_correction  # recover true temperature
    dewpoint_depression = np.abs(np.random.normal(4.0, 1.5, (nlat, nlon)))
    dewpoint_depression = np.clip(dewpoint_depression, 0.5, 15.0)
    d2m[t] = true_temp - dewpoint_depression

# sp: surface pressure in Pa (no data quality issues)
sp = np.zeros((ntime, nlat, nlon), dtype=np.float64)
for t in range(ntime):
    base_pressure = 101325 - 300 * np.sin(2 * lat_rad)
    noise = np.random.normal(0, 200, (nlat, nlon))
    sp[t] = base_pressure[:, np.newaxis] + noise

# tp: total precipitation in m accumulated per month
tp = np.zeros((ntime, nlat, nlon), dtype=np.float64)
for t in range(ntime):
    itcz = 0.15 * np.exp(-lat_rad**2 / 0.3)
    storm = (0.08 * np.exp(-(lat_rad - 0.8)**2 / 0.2) +
             0.08 * np.exp(-(lat_rad + 0.8)**2 / 0.2))
    base_pr = itcz + storm
    noise = np.abs(np.random.normal(0, 0.02, (nlat, nlon)))
    tp[t] = base_pr[:, np.newaxis] + noise
    fill_indices = np.random.choice(nlat * nlon, size=50, replace=False)
    tp[t].flat[fill_indices] = -9999.0

# ssrd: surface solar radiation downwards in J/m2 accumulated per month
ssrd = np.zeros((ntime, nlat, nlon), dtype=np.float64)
for t in range(ntime):
    month = t % 12
    declination = 23.44 * np.sin(2 * np.pi * (month + 9) / 12.0)
    solar_factor = np.cos(lat_rad - np.radians(declination))
    solar_factor = np.maximum(solar_factor, 0)
    base_flux = 250 * solar_factor
    noise = np.random.normal(0, 15, (nlat, nlon))
    flux_wm2 = np.maximum(base_flux[:, np.newaxis] + noise, 0)
    ssrd[t] = flux_wm2 * month_secs[t]

# Write main raw data file
os.makedirs('/data/raw_data', exist_ok=True)
filepath = '/data/raw_data/synthetic_era5_monthly_2000_2002.nc'

with nc.Dataset(filepath, 'w', format='NETCDF4') as ds:
    ds.createDimension('time', None)
    ds.createDimension('latitude', nlat)
    ds.createDimension('longitude', nlon)

    time_var = ds.createVariable('time', 'f8', ('time',))
    time_var.units = 'hours since 1900-01-01 00:00:00'
    time_var.calendar = 'standard'
    time_var.long_name = 'time'
    time_var[:] = time_vals

    lat_var = ds.createVariable('latitude', 'f8', ('latitude',))
    lat_var.units = 'degrees_north'
    lat_var.long_name = 'latitude'
    lat_var[:] = lat

    lon_var = ds.createVariable('longitude', 'f8', ('longitude',))
    lon_var.units = 'degrees_east'
    lon_var.long_name = 'longitude'
    lon_var[:] = lon

    t2m_var = ds.createVariable('t2m', 'f8', ('time', 'latitude', 'longitude'))
    t2m_var.units = 'K'
    t2m_var.long_name = '2 metre temperature'
    t2m_var[:] = t2m

    d2m_var = ds.createVariable('d2m', 'f8', ('time', 'latitude', 'longitude'))
    d2m_var.units = 'K'
    d2m_var.long_name = '2 metre dewpoint temperature'
    d2m_var[:] = d2m

    sp_var = ds.createVariable('sp', 'f8', ('time', 'latitude', 'longitude'))
    sp_var.units = 'Pa'
    sp_var.long_name = 'Surface pressure'
    sp_var[:] = sp

    tp_var = ds.createVariable('tp', 'f8', ('time', 'latitude', 'longitude'))
    tp_var.units = 'm'
    tp_var.long_name = 'Total precipitation'
    tp_var[:] = tp

    ssrd_var = ds.createVariable('ssrd', 'f8', ('time', 'latitude', 'longitude'))
    ssrd_var.units = 'J m**-2'
    ssrd_var.long_name = 'Surface solar radiation downwards'
    ssrd_var[:] = ssrd

    ds.source = 'Synthetic ERA5-like reanalysis'
    ds.history = 'Generated for CMORization exercise'

# Write ancillary orography difference file
os.makedirs('/data/ancillary', exist_ok=True)
orog_path = '/data/ancillary/orog_diff.nc'

with nc.Dataset(orog_path, 'w', format='NETCDF4') as ds:
    ds.createDimension('latitude', nlat)
    ds.createDimension('longitude', nlon)

    lat_var = ds.createVariable('latitude', 'f8', ('latitude',))
    lat_var.units = 'degrees_north'
    lat_var.long_name = 'latitude'
    lat_var[:] = lat

    lon_var = ds.createVariable('longitude', 'f8', ('longitude',))
    lon_var.units = 'degrees_east'
    lon_var.long_name = 'longitude'
    lon_var[:] = lon

    orog_var = ds.createVariable('orog_diff', 'f8', ('latitude', 'longitude'))
    orog_var.units = 'm'
    orog_var.long_name = 'Model orography minus true surface elevation'
    orog_var[:] = orog_diff

    ds.description = 'Orography difference field for lapse rate temperature correction'

print('Synthetic data generated successfully.')
