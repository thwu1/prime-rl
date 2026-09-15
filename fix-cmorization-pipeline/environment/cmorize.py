#!/usr/bin/env python3
"""CMORization pipeline for converting raw observational data to CMOR format.

Reads raw climate NetCDF files, applies coordinate transformations, unit
conversions, and metadata standardization, and writes CMOR-compliant output.
"""
import json
import os
import sys
import numpy as np
import netCDF4 as nc
from utils import (shift_longitude, flip_latitudes, compute_bounds,
                   standardize_time, convert_units, handle_missing_values)


def load_cmor_spec(spec_path):
    """Load CMOR specification from JSON file."""
    with open(spec_path) as f:
        return json.load(f)


def process_variable(var_name, spec, raw_dir, output_dir):
    """Process a single variable through the CMORization pipeline."""
    var_spec = spec['variables'][var_name]
    coord_spec = spec['coordinates']

    raw_file = os.path.join(raw_dir, var_spec['raw_file'])
    raw_name = var_spec['raw_name']

    print(f"Processing {var_name} from {raw_file}...")

    # Open raw data
    ds = nc.Dataset(raw_file, 'r')

    # Identify dimension names (handle lat/latitude, lon/longitude variants)
    raw_var = ds.variables[raw_name]
    dim_names = raw_var.dimensions

    lat_dim = None
    lon_dim = None
    for d in dim_names:
        if d in ('lat', 'latitude'):
            lat_dim = d
        elif d in ('lon', 'longitude'):
            lon_dim = d

    # Read raw data and coordinates
    data = raw_var[:].data.copy()
    lat_values = ds.variables[lat_dim][:].data.copy()
    lon_values = ds.variables[lon_dim][:].data.copy()
    time_values = ds.variables['time'][:].data.copy()
    time_units = ds.variables['time'].units
    time_calendar = getattr(ds.variables['time'], 'calendar', 'standard')

    lat_axis = list(dim_names).index(lat_dim)
    lon_axis = list(dim_names).index(lon_dim)

    # Get fill value from raw data
    raw_fill = getattr(raw_var, '_FillValue', None)
    if raw_fill is not None:
        raw_fill = float(raw_fill)

    source_units = ds.variables[raw_name].units

    ds.close()

    # === Processing Pipeline ===

    # Step 1: Convert units
    data = convert_units(data, source_units, var_spec['units'])

    # Step 2: Handle missing values
    if raw_fill is not None:
        data, mask = handle_missing_values(data, raw_fill)
    else:
        # Check for common undeclared fill values
        data, mask = handle_missing_values(data, -9999.0)

    # Step 3: Clip unphysical values for precipitation
    if var_name == 'pr':
        valid_mask = ~(data >= 1.0e20)
        data[valid_mask & (data < 0)] = 0.0

    # Step 4: Shift longitude if needed
    if np.any(lon_values < 0):
        lon_values, data = shift_longitude(lon_values, data, lon_axis)

    # Step 5: Flip latitudes if needed
    lat_values, data = flip_latitudes(lat_values, data, lat_axis)

    # Step 6: Standardize time
    target_time_units = coord_spec['time']['units']
    target_calendar = coord_spec['time']['calendar']
    time_values, time_bounds = standardize_time(
        time_values, time_units, time_calendar,
        target_time_units, target_calendar
    )

    # Step 7: Compute coordinate bounds
    lat_bounds = compute_bounds(lat_values)
    lon_bounds = compute_bounds(lon_values)

    # Step 8: Convert data types
    data = data.astype(np.float32)
    lat_values = lat_values.astype(np.float64)
    lon_values = lon_values.astype(np.float64)
    lat_bounds = lat_bounds.astype(np.float64)
    lon_bounds = lon_bounds.astype(np.float64)
    time_values = time_values.astype(np.float64)

    # Step 9: Write output
    write_output(var_name, var_spec, spec, data,
                 lat_values, lon_values, time_values,
                 lat_bounds, lon_bounds, time_bounds,
                 output_dir)

    print(f"  Done: {var_name}")


def get_raw_units(var_spec):
    """Read units string from the raw data file."""
    raw_file = os.path.join('/app/raw_data', var_spec['raw_file'])
    ds = nc.Dataset(raw_file, 'r')
    units = ds.variables[var_spec['raw_name']].units
    ds.close()
    return units


def write_output(var_name, var_spec, spec, data,
                 lat_values, lon_values, time_values,
                 lat_bounds, lon_bounds, time_bounds,
                 output_dir):
    """Write CMOR-compliant NetCDF output file."""
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir,
                                f"{var_name}_Amon_OBS_2001.nc")

    ds = nc.Dataset(output_file, 'w', format='NETCDF4')

    # Dimensions
    ds.createDimension('time', None)
    ds.createDimension('lat', len(lat_values))
    ds.createDimension('lon', len(lon_values))
    ds.createDimension('bnds', 2)

    # Time coordinate
    time_var = ds.createVariable('time', 'f8', ('time',))
    time_var.units = spec['coordinates']['time']['units']
    time_var.calendar = spec['coordinates']['time']['calendar']
    time_var.axis = 'T'
    time_var.standard_name = 'time'
    time_var[:] = time_values

    if time_bounds is not None:
        time_var.bounds = 'time_bnds'
        time_bnds = ds.createVariable('time_bnds', 'f8', ('time', 'bnds'))
        time_bnds[:] = time_bounds

    # Latitude coordinate
    lat_var = ds.createVariable('lat', 'f8', ('lat',))
    lat_var.units = 'degrees_north'
    lat_var.standard_name = 'latitude'
    lat_var.axis = 'Y'
    lat_var.bounds = 'lat_bnds'
    lat_var[:] = lat_values

    lat_bnds = ds.createVariable('lat_bnds', 'f8', ('lat', 'bnds'))
    lat_bnds[:] = lat_bounds

    # Longitude coordinate
    lon_var = ds.createVariable('lon', 'f8', ('lon',))
    lon_var.units = 'degrees_east'
    lon_var.standard_name = 'longitude'
    lon_var.axis = 'X'
    lon_var.bounds = 'lon_bnds'
    lon_var[:] = lon_values

    lon_bnds = ds.createVariable('lon_bnds', 'f8', ('lon', 'bnds'))
    lon_bnds[:] = lon_bounds

    # Data variable
    data_var = ds.createVariable(var_name, 'f4', ('time', 'lat', 'lon'),
                                  fill_value=np.float32(1.0e20))
    data_var.standard_name = var_spec['standard_name']
    data_var.long_name = var_spec['long_name']
    data_var.units = get_raw_units(var_spec)

    if var_spec.get('positive'):
        data_var.positive = var_spec['positive']

    data_var[:] = data

    # Global attributes
    ds.source = 'Synthetic observational data (CMORized)'
    ds.table_id = spec['header']['table_id']
    ds.frequency = var_spec['frequency']

    ds.close()


def main():
    spec = load_cmor_spec('/app/cmor_spec.json')
    raw_dir = '/app/raw_data'
    output_dir = '/app/output'

    for var_name in spec['variables']:
        try:
            process_variable(var_name, spec, raw_dir, output_dir)
        except Exception as e:
            print(f"ERROR processing {var_name}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)

    print("CMORization complete.")


if __name__ == '__main__':
    main()
