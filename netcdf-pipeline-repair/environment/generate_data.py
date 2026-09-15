#!/usr/bin/env python3
"""Generate synthetic climate observation netCDF files with embedded data quality issues."""
import numpy as np
import netCDF4 as nc
import os

os.makedirs('/app/data', exist_ok=True)

# Grid definition
lats = np.array([-75.0, -45.0, -15.0, 15.0, 45.0, 75.0])
lons = np.array([22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5])
nlat, nlon = len(lats), len(lons)
ntime = 12

# Time values: mid-month day offsets from 2018-01-01
days_2018 = np.array([15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349],
                     dtype=np.float64)
days_2019 = days_2018 + 365.0
days_2020 = days_2019 + 365.0

# Ocean mask (fixed spatial pattern)
ocean_mask = np.zeros((nlat, nlon), dtype=bool)
ocean_mask[0, :] = True     # lat=-75: all ocean
ocean_mask[5, :] = True     # lat=75: all ocean
ocean_mask[2, 4:7] = True   # lat=-15, lon indices 4-6: partial ocean

np.random.seed(42)


def generate_fields():
    """Generate physically plausible temperature and humidity fields."""
    tas = np.zeros((ntime, nlat, nlon), dtype=np.float32)
    huss = np.zeros((ntime, nlat, nlon), dtype=np.float32)

    for t in range(ntime):
        for j in range(nlat):
            for i in range(nlon):
                T = (288.0
                     + 20.0 * np.sin(np.radians(lats[j]))
                     - 10.0 * np.cos(2.0 * np.pi * t / 12.0)
                     + 2.0 * np.sin(np.radians(lons[i]))
                     + np.random.normal(0, 1.5))
                tas[t, j, i] = T

                T_C = T - 273.15
                es = 611.2 * np.exp(17.67 * T_C / (T_C + 243.5))
                q = 0.622 * 0.65 * es / 101325.0
                q += np.random.normal(0, 0.0003)
                huss[t, j, i] = max(q, 1e-5)

    return tas, huss


def apply_mask(data, fill_val):
    """Set ocean cells to the given fill value."""
    masked = data.copy()
    for t in range(data.shape[0]):
        masked[t][ocean_mask] = fill_val
    return masked


# ============================================================
# File 1: obs_2018.nc
# ============================================================
tas_2018, huss_2018 = generate_fields()

ds = nc.Dataset('/app/data/obs_2018.nc', 'w', format='NETCDF4')
ds.createDimension('time', None)
ds.createDimension('lat', nlat)
ds.createDimension('lon', nlon)

tv = ds.createVariable('time', 'f8', ('time',))
tv.units = 'days since 2018-01-01'
tv.calendar = 'standard'
tv[:] = days_2018

latv = ds.createVariable('lat', 'f8', ('lat',))
latv.units = 'degrees_north'
latv.long_name = 'latitude'
latv[:] = lats

lonv = ds.createVariable('lon', 'f8', ('lon',))
lonv.units = 'degrees_east'
lonv.long_name = 'longitude'
lonv[:] = lons

tasv = ds.createVariable('tas', 'f4', ('time', 'lat', 'lon'),
                         fill_value=np.float32('nan'))
tasv.units = 'K'
tasv.long_name = 'Near-Surface Air Temperature'
tasv[:] = apply_mask(tas_2018, np.float32('nan'))

hussv = ds.createVariable('huss', 'f4', ('time', 'lat', 'lon'),
                          fill_value=np.float32(1.0e20))
hussv.units = 'kg kg-1'
hussv.long_name = 'Near-Surface Specific Humidity'
hussv[:] = apply_mask(huss_2018, np.float32(1.0e20))

ds.Conventions = 'CF-1.8'
ds.close()

# ============================================================
# File 2: obs_2019.nc
# ============================================================
tas_2019, huss_2019 = generate_fields()

ds = nc.Dataset('/app/data/obs_2019.nc', 'w', format='NETCDF4')
ds.createDimension('time', None)
ds.createDimension('lat', nlat)
ds.createDimension('lon', nlon)

tv = ds.createVariable('time', 'f8', ('time',))
tv.units = 'days since 2018-01-01'
tv.calendar = 'standard'
corrupt_days = days_2019.copy()
corrupt_days[6] = -999.0
tv[:] = corrupt_days

latv = ds.createVariable('lat', 'f8', ('lat',))
latv.units = 'degrees_north'
latv.long_name = 'latitude'
latv[:] = lats

lonv = ds.createVariable('lon', 'f8', ('lon',))
lonv.units = 'degrees_east'
lonv.long_name = 'longitude'
lonv[:] = lons

tasv = ds.createVariable('tas', 'f4', ('time', 'lat', 'lon'),
                         fill_value=np.float32(1.0e20))
tasv.units = 'K'
tasv.long_name = 'Near-Surface Air Temperature'
tas_corrupt = apply_mask(tas_2019, np.float32(1.0e20))
tas_corrupt[6, :, :] = np.float32(1.0e20)
tasv[:] = tas_corrupt

hussv = ds.createVariable('huss', 'f4', ('time', 'lat', 'lon'),
                          fill_value=np.float32(1.0e20))
hussv.units = 'kg kg-1'
hussv.long_name = 'Near-Surface Specific Humidity'
huss_corrupt = apply_mask(huss_2019, np.float32(1.0e20))
huss_corrupt[6, :, :] = np.float32(1.0e20)
hussv[:] = huss_corrupt

ds.Conventions = 'CF-1.8'
ds.close()

# ============================================================
# File 3: obs_2020.nc
# ============================================================
tas_2020, huss_2020 = generate_fields()

ds = nc.Dataset('/app/data/obs_2020.nc', 'w', format='NETCDF4')
ds.createDimension('time', None)
ds.createDimension('y', nlat)
ds.createDimension('x', nlon)

tv = ds.createVariable('time', 'f8', ('time',))
tv.units = 'days since 2018-01-01'
tv.calendar = 'standard'
tv[:] = days_2020

latv = ds.createVariable('nav_lat', 'f8', ('y',))
latv.units = 'degrees_north'
latv[:] = lats

lonv = ds.createVariable('nav_lon', 'f8', ('x',))
lonv.units = 'degrees_east'
lonv[:] = lons

tasv = ds.createVariable('tas', 'f4', ('time', 'y', 'x'),
                         fill_value=np.float32(1.0e20))
tasv.units = 'K'
tasv.long_name = 'Near-Surface Air Temperature'
tasv[:] = apply_mask(tas_2020, np.float32(1.0e20))

hussv = ds.createVariable('huss', 'f4', ('time', 'y', 'x'),
                          fill_value=np.float32(-9999.0))
hussv.units = 'kg kg-1'
hussv.long_name = 'Near-Surface Specific Humidity'
hussv.missing_value = np.float32(1.0e30)
hussv[:] = apply_mask(huss_2020, np.float32(-9999.0))

ds.close()

print("Generated: obs_2018.nc, obs_2019.nc, obs_2020.nc in /app/data/")
