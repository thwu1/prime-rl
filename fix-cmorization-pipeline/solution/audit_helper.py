#!/usr/bin/env python3
"""Compute CMOR compliance audit for both pipelines.


Inspects output files from Pipeline Alpha and Pipeline Beta to determine
which compliance dimensions each pipeline handles correctly, and provides
root cause analysis and processing dependency information.
"""
import json
import os
import numpy as np
import netCDF4 as nc

SPEC_PATH = '/app/cmor_spec.json'
VARIABLES = ['tas', 'pr', 'rlut']


def load_spec():
    with open(SPEC_PATH) as f:
        return json.load(f)


def check_spatial_alignment(output_dir):
    path = os.path.join(output_dir, 'tas_Amon_OBS_2001.nc')
    ds = nc.Dataset(path, 'r')
    data = ds.variables['tas'][0]
    lon = ds.variables['lon'][:]
    lat = ds.variables['lat'][:]
    ds.close()
    eq_mask = (lat >= -15) & (lat <= 15)
    idx_0 = int(np.argmin(np.abs(lon - 2.5)))
    idx_180 = int(np.argmin(np.abs(lon - 182.5)))
    mean_0 = float(np.mean(data[eq_mask, idx_0]))
    mean_180 = float(np.mean(data[eq_mask, idx_180]))
    return mean_0 > mean_180


def check_unit_conversion(output_dir):
    path = os.path.join(output_dir, 'pr_Amon_OBS_2001.nc')
    ds = nc.Dataset(path, 'r')
    ds.set_auto_mask(False)
    data = ds.variables['pr'][:]
    ds.close()
    valid = data[data < 1.0e19]
    if len(valid) == 0:
        return False
    return float(np.max(valid)) < 0.01


def check_unit_strings(output_dir):
    spec = load_spec()
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        ds = nc.Dataset(path, 'r')
        actual = ds.variables[var].units
        ds.close()
        if actual != spec['variables'][var]['units']:
            return False
    return True


def check_lat_bounds_polar(output_dir):
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        ds = nc.Dataset(path, 'r')
        lb = ds.variables['lat_bnds'][:]
        ds.close()
        if lb[0, 0] > -89.0 or lb[-1, 1] < 89.0:
            return False
    return True


def check_time_bounds(output_dir):
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        ds = nc.Dataset(path, 'r')
        has_tb = 'time_bnds' in ds.variables
        correct_shape = False
        if has_tb:
            tb = ds.variables['time_bnds'][:]
            correct_shape = (tb.shape == (12, 2))
        ds.close()
        if not has_tb or not correct_shape:
            return False
    return True


def check_missing_values(output_dir):
    path = os.path.join(output_dir, 'pr_Amon_OBS_2001.nc')
    ds = nc.Dataset(path, 'r')
    ds.set_auto_mask(False)
    data = ds.variables['pr'][:]
    fill_val = ds.variables['pr']._FillValue
    ds.close()
    n_fill = int(np.sum(np.isclose(data, fill_val, rtol=1e-5)))
    return n_fill / data.size > 0.01


def check_global_attributes(output_dir):
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        ds = nc.Dataset(path, 'r')
        has_conv = hasattr(ds, 'Conventions')
        has_hist = hasattr(ds, 'history')
        ds.close()
        if not has_conv or not has_hist:
            return False
    return True


def check_variable_attributes(output_dir):
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        ds = nc.Dataset(path, 'r')
        has_cm = hasattr(ds.variables[var], 'cell_methods')
        ds.close()
        if not has_cm:
            return False
    return True


CHECKERS = {
    'spatial_alignment': check_spatial_alignment,
    'unit_conversion': check_unit_conversion,
    'unit_strings': check_unit_strings,
    'lat_bounds_polar': check_lat_bounds_polar,
    'time_bounds': check_time_bounds,
    'missing_values': check_missing_values,
    'global_attributes': check_global_attributes,
    'variable_attributes': check_variable_attributes,
}

# Root cause explanations and affected variables for known defects
ALPHA_DEFECTS = {
    'unit_conversion': {
        'root_cause': 'convert_units multiplies mm/day by 86400 instead of dividing, producing precipitation values approximately 7.5 million times too large',
        'affected_variables': ['pr']
    },
    'lat_bounds_polar': {
        'root_cause': 'compute_bounds uses symmetric extrapolation without polar extension; for the Gaussian-like rlut grid whose outermost points are at +/-80.27, extrapolated bounds only reach +/-83.7 instead of +/-90',
        'affected_variables': ['rlut']
    },
    'missing_values': {
        'root_cause': 'fill value detection (np.isclose check for -9999.0) is performed after unit conversion, at which point the sentinel -9999.0 has been multiplied by 86400 to become -863913600 and is no longer detectable',
        'affected_variables': ['pr']
    },
    'global_attributes': {
        'root_cause': 'write_output omits CF-required Conventions and history global attributes from the output NetCDF files',
        'affected_variables': ['tas', 'pr', 'rlut']
    },
}

BETA_DEFECTS = {
    'spatial_alignment': {
        'root_cause': 'shift_longitude sorts longitude coordinate values via argsort but does not apply np.take to reorder the data array along the longitude axis, decoupling data from its coordinates',
        'affected_variables': ['tas']
    },
    'unit_strings': {
        'root_cause': 'write_output calls get_raw_units to read the unit string from the raw input file instead of using the CMOR spec target units, writing non-CF strings like degC and mm/day',
        'affected_variables': ['tas', 'pr', 'rlut']
    },
    'time_bounds': {
        'root_cause': 'standardize_time returns None for time_bounds instead of computing monthly start/end bounds, so no time_bnds variable is written to the output',
        'affected_variables': ['tas', 'pr', 'rlut']
    },
    'variable_attributes': {
        'root_cause': 'write_output does not set the cell_methods attribute on data variables, omitting CF-required metadata for temporal/spatial aggregation',
        'affected_variables': ['tas', 'pr', 'rlut']
    },
}


def audit_pipeline(output_dir, known_defects):
    result = {}
    for dim, checker in CHECKERS.items():
        result[dim] = checker(output_dir)
    result['pass_count'] = sum(1 for k, v in result.items() if v is True)

    defect_analysis = {}
    for dim in CHECKERS:
        if not result[dim] and dim in known_defects:
            defect_analysis[dim] = known_defects[dim]
    result['defect_analysis'] = defect_analysis

    return result


def main():
    alpha = audit_pipeline('/app/output_alpha', ALPHA_DEFECTS)
    beta = audit_pipeline('/app/output_beta', BETA_DEFECTS)

    if alpha['pass_count'] > beta['pass_count']:
        superior = 'alpha'
    elif beta['pass_count'] > alpha['pass_count']:
        superior = 'beta'
    else:
        superior = 'neither'

    processing_dependencies = [
        {
            'earlier': 'fill value / sentinel detection',
            'later': 'unit conversion',
            'rationale': 'Undeclared sentinel values (e.g. -9999.0) must be identified before any arithmetic transformation; Pipeline Alpha converts units first, transforming -9999.0 to -863913600 via multiplication by 86400, after which the sentinel check for -9999.0 finds nothing and fill values are silently treated as valid data'
        },
        {
            'earlier': 'coordinate reordering (argsort)',
            'later': 'data array access by coordinate index',
            'rationale': 'When longitude coordinates are shifted from [-180,180] to [0,360] and sorted, the data array must be reordered in the same way using np.take; Pipeline Beta sorts coordinates but not data, so data at original longitude index 0 (lon=-177.5, now mapped to 182.5) remains at array position 0 while the coordinate says position 0 is lon=2.5, corrupting all spatial lookups'
        }
    ]

    report = {
        'pipeline_alpha': alpha,
        'pipeline_beta': beta,
        'processing_dependencies': processing_dependencies,
        'superior_pipeline': superior,
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Audit report written to /app/audit_report.json")
    print(f"  Alpha: {alpha['pass_count']}/8 passed")
    print(f"  Beta:  {beta['pass_count']}/8 passed")
    print(f"  Superior: {superior}")


if __name__ == '__main__':
    main()
