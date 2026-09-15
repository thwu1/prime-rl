#!/usr/bin/env python3
"""CMORize synthetic ERA5-like reanalysis data to CMIP-compliant format."""


import json
import numpy as np
import netCDF4 as nc
import os
import calendar
from datetime import datetime, timedelta

# Load CMOR specification
with open('/data/cmor_spec.json') as f:
    spec = json.load(f)

# Open raw data
raw_ds = nc.Dataset('/data/raw_data/synthetic_era5_monthly_2000_2002.nc', 'r')

# Open ancillary orography difference
orog_ds = nc.Dataset('/data/ancillary/orog_diff.nc', 'r')
orog_diff = orog_ds.variables['orog_diff'][:].copy()
orog_ds.close()

# ---- COORDINATE TRANSFORMATIONS ----

raw_lat = raw_ds.variables['latitude'][:]   # 90 to -90 (descending)
raw_lon = raw_ds.variables['longitude'][:]  # -180 to 177.5
raw_time = raw_ds.variables['time'][:]      # hours since 1900-01-01

# 1. Latitude: flip to ascending (-90 to 90)
new_lat = raw_lat[::-1].astype(np.float64)

# 2. Longitude: wrap -180..180 to 0..360
new_lon = raw_lon.copy().astype(np.float64)
new_lon[new_lon < 0] += 360.0
lon_sort_idx = np.argsort(new_lon)
new_lon = new_lon[lon_sort_idx]

# 3. Time: decode raw times to datetimes
raw_base = datetime(1900, 1, 1)
dates = [raw_base + timedelta(hours=float(h)) for h in raw_time]

# Convert to output reference: days since 1850-01-01
out_base = datetime(1850, 1, 1)

# Compute time bounds (full calendar month) and seconds per month
ntime = len(dates)
time_bounds = np.zeros((ntime, 2), dtype=np.float64)
seconds_per_month = np.zeros(ntime, dtype=np.float64)

for i, d in enumerate(dates):
    yr, mo = d.year, d.month
    month_start = datetime(yr, mo, 1)
    month_end = datetime(yr + 1, 1, 1) if mo == 12 else datetime(yr, mo + 1, 1)
    time_bounds[i, 0] = (month_start - out_base).total_seconds() / 86400.0
    time_bounds[i, 1] = (month_end - out_base).total_seconds() / 86400.0
    seconds_per_month[i] = calendar.monthrange(yr, mo)[1] * 86400.0

# Time values at mid-month (center of bounds)
new_time = (time_bounds[:, 0] + time_bounds[:, 1]) / 2.0

# 4. Coordinate bounds
dlat = abs(new_lat[1] - new_lat[0]) / 2.0
lat_bounds = np.zeros((len(new_lat), 2), dtype=np.float64)
for i in range(len(new_lat)):
    lat_bounds[i, 0] = max(new_lat[i] - dlat, -90.0)
    lat_bounds[i, 1] = min(new_lat[i] + dlat, 90.0)

dlon = (new_lon[1] - new_lon[0]) / 2.0
lon_bounds = np.zeros((len(new_lon), 2), dtype=np.float64)
for i in range(len(new_lon)):
    lon_bounds[i, 0] = new_lon[i] - dlon
    lon_bounds[i, 1] = new_lon[i] + dlon

# Global attributes
global_attrs = spec['required_global_attributes'].copy()
global_attrs['history'] = f'CMORized {datetime.now().isoformat()}'

os.makedirs('/app/output', exist_ok=True)

# ---- VARIABLE-SPECIFIC PREPARATION ----

# Standard atmosphere lapse rate: 6.5 K/km = 0.0065 K/m
LAPSE_RATE = 0.0065  # K/m


def prepare_tas():
    """Near-surface air temperature with bias and lapse rate correction."""
    data = raw_ds.variables['t2m'][:].copy()
    # 1. Subtract constant warm bias (+0.5 K)
    data = data - 0.5
    # 2. Apply lapse rate correction for orographic representativeness error
    # T_true_altitude = T_model_altitude + lapse_rate * (z_model - z_true)
    data = data + LAPSE_RATE * orog_diff[np.newaxis, :, :]
    return data


def prepare_huss():
    """Derive near-surface specific humidity from dewpoint temperature and
    surface pressure using standard thermodynamic relationships.

    Uses the Tetens/Magnus formula for saturation vapor pressure at the
    dewpoint temperature, then converts to specific humidity via the
    relationship q = epsilon * e / (p - (1 - epsilon) * e).
    """
    d2m = raw_ds.variables['d2m'][:].copy()
    sp = raw_ds.variables['sp'][:].copy()

    # Saturation vapor pressure at dewpoint (Tetens/Magnus formula)
    # e(T_d) = 611.2 * exp(17.67 * T_c / (T_c + 243.5))  [Pa]
    T_c = d2m - 273.15
    e = 611.2 * np.exp(17.67 * T_c / (T_c + 243.5))

    # Specific humidity: q = epsilon * e / (p - (1-epsilon) * e)
    # where epsilon = Rd/Rv = 287.058/461.5 ~ 0.622
    q = 0.622 * e / (sp - 0.378 * e)

    return q


def prepare_pr():
    """Precipitation flux from monthly accumulated totals."""
    data = raw_ds.variables['tp'][:].copy()
    # Mask fill values (-9999.0) before any conversion
    data = np.ma.masked_equal(data, -9999.0)
    # Convert: m water equivalent per month -> kg m-2 s-1
    # 1 m water = 1000 kg/m2; divide by seconds in month for rate
    for t in range(data.shape[0]):
        data[t] = data[t] * 1000.0 / seconds_per_month[t]
    return data


def prepare_rsds():
    """Surface downwelling shortwave radiation from monthly accumulated energy."""
    data = raw_ds.variables['ssrd'][:].copy()
    # Convert: J m-2 accumulated per month -> W m-2
    for t in range(data.shape[0]):
        data[t] = data[t] / seconds_per_month[t]
    return data


prepare_funcs = {
    'tas': prepare_tas,
    'huss': prepare_huss,
    'pr': prepare_pr,
    'rsds': prepare_rsds,
}

# ---- WRITE OUTPUT FILES ----

for var_name, var_spec in spec['variables'].items():
    print(f'Processing {var_name}')

    data = prepare_funcs[var_name]()

    # Flip latitude (axis 1) -- raw is descending, output must be ascending
    data = data[:, ::-1, :]

    # Reorder longitude (axis 2) -- raw is -180..180, output must be 0..360
    data = data[:, :, lon_sort_idx]

    # Convert to float32
    data = data.astype(np.float32)

    # Build output filename
    start_date = f'{dates[0].year:04d}{dates[0].month:02d}'
    end_date = f'{dates[-1].year:04d}{dates[-1].month:02d}'
    filename = spec['output_filename_template'].format(
        project_id=spec['project_id'],
        dataset_id=spec['dataset_id'],
        data_type=spec['data_type'],
        version=spec['version'],
        mip=spec['mip'],
        variable=var_name,
        start_date=start_date,
        end_date=end_date,
    )
    filepath = os.path.join('/app/output', filename)
    print(f'  -> {filepath}')

    # Write output NetCDF
    with nc.Dataset(filepath, 'w', format='NETCDF4') as ds:
        ds.createDimension('time', None)
        ds.createDimension('lat', len(new_lat))
        ds.createDimension('lon', len(new_lon))
        ds.createDimension('bnds', 2)

        # Time coordinate
        tv = ds.createVariable('time', 'f8', ('time',))
        tv.standard_name = 'time'
        tv.long_name = 'time'
        tv.units = spec['coordinate_conventions']['time']['units']
        tv.calendar = spec['coordinate_conventions']['time']['calendar']
        tv.axis = 'T'
        tv.bounds = 'time_bnds'
        tv[:] = new_time

        tb = ds.createVariable('time_bnds', 'f8', ('time', 'bnds'))
        tb[:] = time_bounds

        # Latitude coordinate
        latv = ds.createVariable('lat', 'f8', ('lat',))
        latv.standard_name = 'latitude'
        latv.long_name = 'latitude'
        latv.units = 'degrees_north'
        latv.axis = 'Y'
        latv.bounds = 'lat_bnds'
        latv[:] = new_lat

        lb = ds.createVariable('lat_bnds', 'f8', ('lat', 'bnds'))
        lb[:] = lat_bounds

        # Longitude coordinate
        lonv = ds.createVariable('lon', 'f8', ('lon',))
        lonv.standard_name = 'longitude'
        lonv.long_name = 'longitude'
        lonv.units = 'degrees_east'
        lonv.axis = 'X'
        lonv.bounds = 'lon_bnds'
        lonv[:] = new_lon

        lob = ds.createVariable('lon_bnds', 'f8', ('lon', 'bnds'))
        lob[:] = lon_bounds

        # Auxiliary scalar coordinates (e.g., height for tas and huss)
        if 'auxiliary_coordinates' in var_spec:
            for cname, cspec in var_spec['auxiliary_coordinates'].items():
                cv = ds.createVariable(cname, 'f8', ())
                cv[...] = cspec['value']
                cv.units = cspec['units']
                cv.standard_name = cspec['standard_name']
                cv.long_name = cspec['long_name']
                cv.axis = cspec['axis']
                cv.positive = cspec['positive']

        # Data variable
        fill_val = np.float32(1e20)
        dv = ds.createVariable(var_name, 'f4', ('time', 'lat', 'lon'),
                               fill_value=fill_val)
        dv.standard_name = var_spec['standard_name']
        dv.long_name = var_spec['long_name']
        dv.units = var_spec['units']
        dv.cell_methods = var_spec['cell_methods']
        if var_spec.get('comment'):
            dv.comment = var_spec['comment']
        if var_spec.get('positive'):
            dv.positive = var_spec['positive']
        if 'auxiliary_coordinates' in var_spec:
            dv.coordinates = ' '.join(var_spec['auxiliary_coordinates'].keys())

        dv[:] = data

        # Global attributes
        for attr_name, attr_val in global_attrs.items():
            ds.setncattr(attr_name, attr_val)

raw_ds.close()
print('CMORization complete.')
