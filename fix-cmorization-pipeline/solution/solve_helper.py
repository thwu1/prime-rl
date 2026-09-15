#!/usr/bin/env python3
"""Corrected CMORization pipeline.


This standalone script correctly converts the three raw climate datasets
in /app/raw_data/ to CMOR-compliant NetCDF output in /app/output/.

It fixes all issues present in the original /app/cmorize.py + /app/utils.py:
  1. Longitude shift now reorders data array alongside coordinates
  2. Precipitation unit conversion divides by 86400 (not multiplies)
  3. Latitude bounds extend to +/-90 for global grids
  4. Monthly time bounds are computed
  5. Fill values are masked BEFORE unit conversion
  6. Output units come from CMOR spec, not raw files
  7. Required CF attributes (Conventions, history, cell_methods) are written
"""
import json
import os
import numpy as np
import netCDF4 as nc
import cftime
from datetime import datetime


def load_spec(path):
    with open(path) as f:
        return json.load(f)


def shift_longitude(lon_values, data, lon_axis):
    """Shift longitude from [-180, 180] to [0, 360] and reorder data."""
    new_lon = np.where(lon_values < 0, lon_values + 360, lon_values)
    sort_idx = np.argsort(new_lon)
    new_lon = new_lon[sort_idx]
    data = np.take(data, sort_idx, axis=lon_axis)
    return new_lon, data


def flip_latitudes(lat_values, data, lat_axis):
    """Ensure latitudes are ascending; flip data if needed."""
    if lat_values[0] > lat_values[-1]:
        lat_values = lat_values[::-1]
        data = np.flip(data, axis=lat_axis)
    return lat_values, data


def compute_bounds(coord_values, is_latitude=False):
    """Compute coordinate bounds with optional polar extension."""
    n = len(coord_values)
    bounds = np.zeros((n, 2))
    midpoints = (coord_values[:-1] + coord_values[1:]) / 2.0
    first_spacing = midpoints[0] - coord_values[0]
    last_spacing = coord_values[-1] - midpoints[-1]

    bounds[0, 0] = coord_values[0] - first_spacing
    bounds[0, 1] = midpoints[0]
    bounds[-1, 0] = midpoints[-1]
    bounds[-1, 1] = coord_values[-1] + last_spacing

    for i in range(1, n - 1):
        bounds[i, 0] = midpoints[i - 1]
        bounds[i, 1] = midpoints[i]

    if is_latitude:
        bounds[0, 0] = -90.0
        bounds[-1, 1] = 90.0

    return bounds


def standardize_time(time_values, source_units, source_calendar,
                     target_units, target_calendar):
    """Convert time to target encoding and compute monthly bounds."""
    source_dates = cftime.num2date(time_values, source_units, source_calendar)

    converted_dates = []
    for d in source_dates:
        if source_calendar == '360_day' and target_calendar in (
                'standard', 'gregorian'):
            new_date = datetime(d.year, d.month, min(d.day, 28))
        else:
            new_date = datetime(d.year, d.month, d.day,
                                d.hour, d.minute, d.second)
        converted_dates.append(new_date)

    target_values = cftime.date2num(converted_dates, target_units,
                                     target_calendar)

    # Compute monthly time bounds: [start_of_month, start_of_next_month]
    time_bounds = np.zeros((len(converted_dates), 2))
    for i, d in enumerate(converted_dates):
        start = datetime(d.year, d.month, 1)
        if d.month == 12:
            end = datetime(d.year + 1, 1, 1)
        else:
            end = datetime(d.year, d.month + 1, 1)
        time_bounds[i, 0] = cftime.date2num(start, target_units,
                                              target_calendar)
        time_bounds[i, 1] = cftime.date2num(end, target_units,
                                              target_calendar)

    return target_values, time_bounds


def convert_units(data, source_units, target_units):
    """Convert data units."""
    if source_units == 'degC' and target_units == 'K':
        return data + 273.15
    elif source_units == 'mm/day' and target_units == 'kg m-2 s-1':
        return data / 86400.0
    elif source_units == target_units:
        return data
    elif source_units == 'W/m2' and target_units == 'W m-2':
        return data
    else:
        raise ValueError(
            f"Unknown conversion: {source_units} -> {target_units}")


def process_variable(var_name, spec):
    """Process a single variable through the corrected pipeline."""
    var_spec = spec['variables'][var_name]
    coord_spec = spec['coordinates']

    raw_file = os.path.join('/app/raw_data', var_spec['raw_file'])
    raw_name = var_spec['raw_name']

    print(f"Processing {var_name} from {raw_file}...")

    ds = nc.Dataset(raw_file, 'r')
    raw_var = ds.variables[raw_name]
    dim_names = raw_var.dimensions

    lat_dim = [d for d in dim_names if d in ('lat', 'latitude')][0]
    lon_dim = [d for d in dim_names if d in ('lon', 'longitude')][0]

    data = raw_var[:].data.copy()
    lat_values = ds.variables[lat_dim][:].data.copy()
    lon_values = ds.variables[lon_dim][:].data.copy()
    time_values = ds.variables['time'][:].data.copy()
    time_units = ds.variables['time'].units
    time_calendar = getattr(ds.variables['time'], 'calendar', 'standard')
    source_units = ds.variables[raw_name].units
    raw_fill = getattr(raw_var, '_FillValue', None)
    if raw_fill is not None:
        raw_fill = float(raw_fill)

    lat_axis = list(dim_names).index(lat_dim)
    lon_axis = list(dim_names).index(lon_dim)

    ds.close()

    # Step 1: Create fill mask BEFORE unit conversion
    fill_mask = np.zeros(data.shape, dtype=bool)
    if raw_fill is not None:
        fill_mask |= np.isclose(data, raw_fill)
    fill_mask |= np.isclose(data, -9999.0)
    fill_mask |= np.isnan(data)

    # Step 2: Convert units
    data = convert_units(data, source_units, var_spec['units'])

    # Step 3: Clip unphysical values (only valid cells)
    if var_name == 'pr':
        valid = ~fill_mask
        data[valid & (data < 0)] = 0.0

    # Step 4: Apply fill mask with CMOR fill value
    data[fill_mask] = 1.0e20

    # Step 5: Shift longitude if needed
    if np.any(lon_values < 0):
        lon_values, data = shift_longitude(lon_values, data, lon_axis)

    # Step 6: Flip latitudes if needed
    lat_values, data = flip_latitudes(lat_values, data, lat_axis)

    # Step 7: Standardize time and compute bounds
    target_time_units = coord_spec['time']['units']
    target_calendar = coord_spec['time']['calendar']
    time_values, time_bounds = standardize_time(
        time_values, time_units, time_calendar,
        target_time_units, target_calendar
    )

    # Step 8: Compute coordinate bounds
    lat_bounds = compute_bounds(lat_values, is_latitude=True)
    lon_bounds = compute_bounds(lon_values)

    # Step 9: Write output
    write_output(var_name, var_spec, spec, data,
                 lat_values, lon_values, time_values,
                 lat_bounds, lon_bounds, time_bounds)

    print(f"  Done: {var_name}")


def write_output(var_name, var_spec, spec, data,
                 lat_values, lon_values, time_values,
                 lat_bounds, lon_bounds, time_bounds):
    """Write CMOR-compliant output."""
    os.makedirs('/app/output', exist_ok=True)
    output_file = f'/app/output/{var_name}_Amon_OBS_2001.nc'

    data = data.astype(np.float32)
    lat_values = lat_values.astype(np.float64)
    lon_values = lon_values.astype(np.float64)
    lat_bounds = lat_bounds.astype(np.float64)
    lon_bounds = lon_bounds.astype(np.float64)
    time_values = time_values.astype(np.float64)
    if time_bounds is not None:
        time_bounds = time_bounds.astype(np.float64)

    ds = nc.Dataset(output_file, 'w', format='NETCDF4')

    ds.createDimension('time', None)
    ds.createDimension('lat', len(lat_values))
    ds.createDimension('lon', len(lon_values))
    ds.createDimension('bnds', 2)

    # Time
    time_var = ds.createVariable('time', 'f8', ('time',))
    time_var.units = spec['coordinates']['time']['units']
    time_var.calendar = spec['coordinates']['time']['calendar']
    time_var.axis = 'T'
    time_var.standard_name = 'time'
    time_var[:] = time_values

    if time_bounds is not None:
        time_var.bounds = 'time_bnds'
        tb_var = ds.createVariable('time_bnds', 'f8', ('time', 'bnds'))
        tb_var[:] = time_bounds

    # Latitude
    lat_var = ds.createVariable('lat', 'f8', ('lat',))
    lat_var.units = 'degrees_north'
    lat_var.standard_name = 'latitude'
    lat_var.axis = 'Y'
    lat_var.bounds = 'lat_bnds'
    lat_var[:] = lat_values

    lb_var = ds.createVariable('lat_bnds', 'f8', ('lat', 'bnds'))
    lb_var[:] = lat_bounds

    # Longitude
    lon_var = ds.createVariable('lon', 'f8', ('lon',))
    lon_var.units = 'degrees_east'
    lon_var.standard_name = 'longitude'
    lon_var.axis = 'X'
    lon_var.bounds = 'lon_bnds'
    lon_var[:] = lon_values

    lob_var = ds.createVariable('lon_bnds', 'f8', ('lon', 'bnds'))
    lob_var[:] = lon_bounds

    # Data variable
    data_var = ds.createVariable(var_name, 'f4', ('time', 'lat', 'lon'),
                                  fill_value=np.float32(1.0e20))
    data_var.standard_name = var_spec['standard_name']
    data_var.long_name = var_spec['long_name']
    data_var.units = var_spec['units']
    data_var.cell_methods = var_spec['cell_methods']
    if var_spec.get('positive'):
        data_var.positive = var_spec['positive']
    data_var[:] = data

    # Global attributes
    ds.Conventions = spec['header']['Conventions']
    ds.history = 'CMORized output'
    ds.source = 'Synthetic observational data (CMORized)'
    ds.table_id = spec['header']['table_id']
    ds.frequency = var_spec['frequency']

    ds.close()


def main():
    spec = load_spec('/app/cmor_spec.json')
    for var_name in spec['variables']:
        process_variable(var_name, spec)
    print("CMORization complete (corrected pipeline).")


if __name__ == '__main__':
    main()
