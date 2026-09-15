#!/usr/bin/env python3
"""Generate synthetic raw climate data files for CMORization task."""
import numpy as np
import netCDF4 as nc
import os
import datetime

os.makedirs('/app/raw_data', exist_ok=True)


def create_tas():
    """Create raw surface air temperature data.

    Issues embedded:
    - Longitude: [-180, 180] range (needs shift to [0, 360])
    - Latitude: descending order (needs flip to ascending)
    - Units: degC (needs conversion to K)
    - Variable name: 'temp_2m' (should be 'tas')
    - Time: 'hours since 2001-01-01' (needs re-encoding)
    - Has longitude-dependent signal for spatial verification
    """
    filepath = '/app/raw_data/temperature_monthly_2001.nc'
    ds = nc.Dataset(filepath, 'w', format='NETCDF4')

    nlat, nlon, ntime = 36, 72, 12

    ds.createDimension('time', None)
    ds.createDimension('lat', nlat)
    ds.createDimension('lon', nlon)

    # Time: hours since 2001-01-01, mid-month
    time_var = ds.createVariable('time', 'f8', ('time',))
    time_var.units = 'hours since 2001-01-01 00:00:00'
    time_var.calendar = 'standard'
    base = datetime.datetime(2001, 1, 1)
    time_vals = []
    for m in range(1, 13):
        mid = datetime.datetime(2001, m, 15)
        delta = mid - base
        time_vals.append(delta.total_seconds() / 3600.0)
    time_var[:] = time_vals

    # Latitude: descending (87.5 to -87.5, 5-degree spacing)
    lat_var = ds.createVariable('lat', 'f8', ('lat',))
    lat_var.units = 'degrees_north'
    lat_var.long_name = 'latitude'
    lat_vals = np.linspace(87.5, -87.5, nlat)
    lat_var[:] = lat_vals

    # Longitude: -177.5 to 177.5 (5-degree spacing, centered)
    lon_var = ds.createVariable('lon', 'f8', ('lon',))
    lon_var.units = 'degrees_east'
    lon_var.long_name = 'longitude'
    lon_vals = np.linspace(-177.5, 177.5, nlon)
    lon_var[:] = lon_vals

    # Temperature in Celsius with longitude-dependent signal
    temp_var = ds.createVariable('temp_2m', 'f8', ('time', 'lat', 'lon'),
                                 fill_value=-9999.0)
    temp_var.units = 'degC'
    temp_var.long_name = '2m air temperature'

    np.random.seed(42)
    lat_rad = np.deg2rad(lat_vals)
    lon_rad = np.deg2rad(lon_vals)
    for t in range(ntime):
        seasonal = 10.0 * np.cos(2.0 * np.pi * (t - 6) / 12.0)
        for j in range(nlat):
            base_temp = 25.0 * np.cos(lat_rad[j]) - 10.0
            base_temp += seasonal * np.cos(lat_rad[j])
            lon_signal = 5.0 * np.cos(lon_rad)
            temp_var[t, j, :] = base_temp + lon_signal + np.random.normal(0, 0.5, nlon)

    ds.title = 'Monthly near-surface temperature'
    ds.source = 'Synthetic observational data'
    ds.close()


def create_pr():
    """Create raw precipitation data.

    Issues embedded:
    - Calendar: 360_day (needs conversion to standard)
    - Units: mm/day (needs conversion to kg m-2 s-1)
    - Variable name: 'precip' (should be 'pr')
    - Dimension names: 'latitude'/'longitude' instead of 'lat'/'lon'
    - Fill value: -9999.0 used but NOT declared in variable metadata
    - Contains negative values from noise (unphysical)
    """
    filepath = '/app/raw_data/precipitation_monthly_2001.nc'
    ds = nc.Dataset(filepath, 'w', format='NETCDF4')

    nlat, nlon, ntime = 72, 144, 12

    ds.createDimension('time', None)
    ds.createDimension('latitude', nlat)
    ds.createDimension('longitude', nlon)

    # Time: 360-day calendar, mid-month
    time_var = ds.createVariable('time', 'f8', ('time',))
    time_var.units = 'days since 2001-01-01'
    time_var.calendar = '360_day'
    time_var[:] = [15 + 30 * m for m in range(12)]

    # Latitude: ascending
    lat_var = ds.createVariable('latitude', 'f8', ('latitude',))
    lat_var.units = 'degrees_north'
    lat_vals = np.linspace(-88.75, 88.75, nlat)
    lat_var[:] = lat_vals

    # Longitude: 0 to 360 range
    lon_var = ds.createVariable('longitude', 'f8', ('longitude',))
    lon_var.units = 'degrees_east'
    lon_vals = np.linspace(1.25, 358.75, nlon)
    lon_var[:] = lon_vals

    # Precipitation in mm/day (NO fill_value declared)
    precip_var = ds.createVariable('precip', 'f8',
                                    ('time', 'latitude', 'longitude'))
    precip_var.units = 'mm/day'
    precip_var.long_name = 'precipitation rate'

    np.random.seed(123)
    for t in range(ntime):
        seasonal = 1.0 + 0.5 * np.cos(2.0 * np.pi * (t - 6) / 12.0)
        for j in range(nlat):
            base_precip = 5.0 * np.exp(-lat_vals[j]**2 / (2.0 * 20.0**2))
            base_precip *= seasonal
            data = base_precip + np.random.normal(0, 1.5, nlon)
            # Polar regions: set some cells to undeclared fill value
            if j < 5 or j > 67:
                mask = np.random.random(nlon) < 0.3
                data[mask] = -9999.0
            precip_var[t, j, :] = data

    ds.title = 'Monthly precipitation rate'
    ds.source = 'Synthetic observational data'
    ds.close()


def create_rlut():
    """Create raw TOA outgoing longwave radiation data.

    Issues embedded:
    - Latitude: Gaussian grid, descending, doesn't extend near ±90
    - Units: 'W/m2' (non-CF, should be 'W m-2')
    - Variable name: 'toa_lw_up' (should be 'rlut')
    - Time: start-of-month instead of mid-month
    """
    filepath = '/app/raw_data/olr_monthly_2001.nc'
    ds = nc.Dataset(filepath, 'w', format='NETCDF4')

    nlat, nlon, ntime = 24, 96, 12

    ds.createDimension('time', None)
    ds.createDimension('lat', nlat)
    ds.createDimension('lon', nlon)

    # Time: standard calendar, start-of-month dates
    time_var = ds.createVariable('time', 'f8', ('time',))
    time_var.units = 'days since 1850-01-01'
    time_var.calendar = 'standard'
    base = datetime.datetime(1850, 1, 1)
    time_vals = []
    for m in range(1, 13):
        dt = datetime.datetime(2001, m, 1)
        time_vals.append((dt - base).days)
    time_var[:] = time_vals

    # Latitude: Gaussian-like grid, descending, NOT reaching poles
    lat_var = ds.createVariable('lat', 'f8', ('lat',))
    lat_var.units = 'degrees_north'
    lat_vals = np.array([
        80.27, 73.48, 66.62, 59.72, 52.80, 45.86,
        38.91, 31.95, 24.98, 18.01, 11.03, 4.05,
        -4.05, -11.03, -18.01, -24.98, -31.95, -38.91,
        -45.86, -52.80, -59.72, -66.62, -73.48, -80.27
    ])
    lat_var[:] = lat_vals

    # Longitude: regular 3.75-degree spacing
    lon_var = ds.createVariable('lon', 'f8', ('lon',))
    lon_var.units = 'degrees_east'
    lon_vals = np.linspace(0, 360.0 - 360.0 / nlon, nlon)
    lon_var[:] = lon_vals

    # OLR in W/m2 (non-CF unit string)
    olr_var = ds.createVariable('toa_lw_up', 'f8', ('time', 'lat', 'lon'),
                                 fill_value=1.0e20)
    olr_var.units = 'W/m2'
    olr_var.long_name = 'top-of-atmosphere outgoing longwave radiation'

    np.random.seed(456)
    lat_rad = np.deg2rad(lat_vals)
    for t in range(ntime):
        seasonal = 5.0 * np.cos(2.0 * np.pi * (t - 1) / 12.0)
        for j in range(nlat):
            base_olr = 240.0 + 40.0 * np.cos(lat_rad[j]) + seasonal
            olr_var[t, j, :] = base_olr + np.random.normal(0, 5, nlon)

    ds.title = 'Monthly TOA outgoing longwave radiation'
    ds.source = 'Synthetic observational data'
    ds.close()


if __name__ == '__main__':
    create_tas()
    create_pr()
    create_rlut()
    print("Raw data created successfully.")
