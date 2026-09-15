#!/usr/bin/env python3
"""CMORizer: transform raw SynthObs data to CMOR-compliant NetCDF4.

Handles:
- Longitude wrapping (-180..180 to 0..360)
- Latitude reordering (N to S  ->  S to N)
- Time epoch conversion (hours since 2000 -> days since 1850)
- Unit conversions (C->K, hPa->Pa)
- Accumulated precipitation deaccumulation with annual reset
- Derived specific humidity from dewpoint temperature
- Quality flag bitmask interpretation and masking
- Coordinate bounds, scalar coordinates, CMOR metadata
"""

import json
import os
import calendar
from datetime import datetime, timedelta

import numpy as np
import netCDF4 as nc


def apply_quality_mask(quality_flags, mask_bits):
    """Create boolean mask from quality flag bitmask.

    Returns True where ANY of the specified mask_bits are set.
    """
    bitmask = 0
    for bit in mask_bits:
        bitmask |= (1 << bit)
    return (quality_flags & bitmask).astype(bool)


def compute_specific_humidity(td_celsius, p_hpa, constants):
    """Compute specific humidity from dewpoint temperature and pressure.

    Magnus formula: e = a * exp(b * Td / (Td + c))
    Specific humidity: q = epsilon * e / (p - (1 - epsilon) * e)
    """
    a = constants['a_hPa']
    b = constants['b']
    c = constants['c_degC']
    eps = constants['epsilon']

    e = a * np.exp(b * td_celsius / (td_celsius + c))
    q = eps * e / (p_hpa - (1 - eps) * e)
    return q


def deaccumulate(tp_acc, time_vals_hours):
    """Deaccumulate time-integrated precipitation.

    Accumulation resets at the start of each calendar year.
    For January (or the first timestep), the accumulated value IS the monthly total.
    For other months, the monthly total is the difference from the previous month.
    """
    ref = datetime(2000, 1, 1)
    ntime = tp_acc.shape[0]
    monthly = np.zeros_like(tp_acc)

    for t in range(ntime):
        dt = ref + timedelta(hours=float(time_vals_hours[t]))
        if dt.month == 1 or t == 0:
            monthly[t] = tp_acc[t]
        else:
            monthly[t] = tp_acc[t] - tp_acc[t - 1]

    return monthly


def get_month_seconds(time_vals_hours):
    """Get number of seconds in each month for unit conversion."""
    ref = datetime(2000, 1, 1)
    ntime = len(time_vals_hours)
    secs = np.zeros(ntime)
    for t in range(ntime):
        dt = ref + timedelta(hours=float(time_vals_hours[t]))
        days = calendar.monthrange(dt.year, dt.month)[1]
        secs[t] = days * 86400.0
    return secs


def main():
    with open('/app/cmor_table.json') as f:
        cmor = json.load(f)

    header = cmor['Header']
    coord_specs = cmor['coordinate_specs']
    data_specs = cmor['data_specs']
    req_attrs = cmor['required_global_attributes']

    raw = nc.Dataset('/app/raw_data/SynthObs_raw.nc', 'r')

    raw_lat = raw.variables['latitude'][:]
    raw_lon = raw.variables['longitude'][:]
    raw_time_vals = raw.variables['time'][:]

    # -- Longitude: wrap [-180, 175] to [0, 355]
    split_idx = int(np.searchsorted(raw_lon, 0))
    new_lon = np.concatenate([raw_lon[split_idx:], raw_lon[:split_idx] + 360.0])

    # -- Latitude: flip N->S to S->N
    lat_flip = bool(raw_lat[0] > raw_lat[-1])
    new_lat = raw_lat[::-1].copy() if lat_flip else raw_lat.copy()

    # -- Time: "hours since 2000-01-01" to "days since 1850-01-01"
    ref_old = datetime(2000, 1, 1)
    ref_new = datetime(1850, 1, 1)
    new_time = np.array([
        (ref_old + timedelta(hours=float(h)) - ref_new).total_seconds() / 86400.0
        for h in raw_time_vals
    ])

    # -- Time bounds
    time_bounds = np.zeros((len(new_time), 2))
    for i, h in enumerate(raw_time_vals):
        dt = ref_old + timedelta(hours=float(h))
        month_start = datetime(dt.year, dt.month, 1)
        if dt.month == 12:
            month_end = datetime(dt.year + 1, 1, 1)
        else:
            month_end = datetime(dt.year, dt.month + 1, 1)
        time_bounds[i, 0] = (month_start - ref_new).total_seconds() / 86400.0
        time_bounds[i, 1] = (month_end - ref_new).total_seconds() / 86400.0

    # -- Coordinate bounds
    lon_step = float(new_lon[1] - new_lon[0])
    lon_bnds = np.column_stack([new_lon - lon_step / 2, new_lon + lon_step / 2])
    lat_step = float(new_lat[1] - new_lat[0])
    lat_bnds = np.column_stack([
        np.maximum(new_lat - lat_step / 2, -90.0),
        np.minimum(new_lat + lat_step / 2, 90.0),
    ])

    # -- Read all raw fields
    fill_val = float(data_specs['fill_value'])
    raw_fill = -9999.0

    raw_t2m = np.array(raw.variables['t2m'][:])
    raw_d2m = np.array(raw.variables['d2m'][:])
    raw_mslp = np.array(raw.variables['mslp'][:])
    raw_tp_acc = np.array(raw.variables['tp_acc'][:])

    qf_t2m = np.array(raw.variables['qf_t2m'][:])
    qf_d2m = np.array(raw.variables['qf_d2m'][:])
    qf_mslp = np.array(raw.variables['qf_mslp'][:])
    qf_tp = np.array(raw.variables['qf_tp'][:])

    # -- Remap coordinates (lon wrap + lat flip)
    def remap(arr):
        out = np.concatenate([arr[:, :, split_idx:], arr[:, :, :split_idx]], axis=2)
        if lat_flip:
            out = out[:, ::-1, :]
        return out

    raw_t2m = remap(raw_t2m)
    raw_d2m = remap(raw_d2m)
    raw_mslp = remap(raw_mslp)
    raw_tp_acc = remap(raw_tp_acc)
    qf_t2m = remap(qf_t2m)
    qf_d2m = remap(qf_d2m)
    qf_mslp = remap(qf_mslp)
    qf_tp = remap(qf_tp)

    # -- Process each variable
    os.makedirs('/app/output', exist_ok=True)

    qf_map = {
        'qf_t2m': qf_t2m, 'qf_d2m': qf_d2m,
        'qf_mslp': qf_mslp, 'qf_tp': qf_tp,
    }

    for cmor_name, vspec in cmor['variable_entry'].items():
        print(f"Processing: {cmor_name}")

        if vspec.get('derived'):
            # Derived variable: specific humidity from dewpoint + pressure
            constants = vspec['derivation_constants']
            data = compute_specific_humidity(raw_d2m, raw_mslp, constants)

            # Quality mask: union of all flag fields
            qc = vspec['quality_control']
            mask = np.zeros(data.shape, dtype=bool)
            for ff in qc['flag_fields']:
                mask |= apply_quality_mask(qf_map[ff], qc['mask_bits'])

            # Missing value mask from inputs
            mask |= np.isclose(raw_d2m, raw_fill)
            mask |= np.isclose(raw_mslp, raw_fill)

        elif vspec.get('raw_field_type') == 'time_accumulated':
            # Deaccumulate precipitation
            monthly_m = deaccumulate(raw_tp_acc, raw_time_vals)

            # Convert m/month to kg m-2 s-1
            month_secs = get_month_seconds(raw_time_vals)
            data = np.zeros_like(monthly_m)
            for t in range(data.shape[0]):
                data[t] = monthly_m[t] * 1000.0 / month_secs[t]

            # Quality mask
            qc = vspec['quality_control']
            mask = apply_quality_mask(qf_map[qc['flag_field']], qc['mask_bits'])

            # Missing value mask (propagate through deaccumulation)
            tp_fill = np.isclose(raw_tp_acc, raw_fill)
            deacc_fill = tp_fill.copy()
            ref = datetime(2000, 1, 1)
            for t in range(1, data.shape[0]):
                dt = ref + timedelta(hours=float(raw_time_vals[t]))
                if dt.month != 1:
                    deacc_fill[t] |= tp_fill[t - 1]
            mask |= deacc_fill

            # Clip negative values
            data = np.maximum(data, 0.0)

        else:
            # Standard variable with unit conversion
            raw_name = vspec['raw_name']
            raw_map = {'t2m': raw_t2m, 'mslp': raw_mslp}
            data = raw_map[raw_name].copy()

            # Quality mask
            qc = vspec['quality_control']
            mask = apply_quality_mask(qf_map[qc['flag_field']], qc['mask_bits'])

            # Missing value mask
            mask |= np.isclose(data, raw_fill)

            # Unit conversion
            if cmor_name == 'tas':
                data = data + 273.15
            elif cmor_name == 'psl':
                data = data * 100.0

        # Apply fill
        data[mask] = fill_val
        data_f32 = data.astype(np.float32)

        # Filename
        start_date = "200001"
        end_date = "200112"
        fname = (f"{header['project_id']}_{header['dataset_id']}_"
                 f"{header['source_type']}_{header['version']}_"
                 f"{header['mip_table']}_{cmor_name}_{start_date}-{end_date}.nc")
        fpath = os.path.join('/app/output', fname)

        # Write NetCDF4
        ds = nc.Dataset(fpath, 'w', format='NETCDF4')
        ds.createDimension('time', None)
        ds.createDimension('latitude', len(new_lat))
        ds.createDimension('longitude', len(new_lon))
        ds.createDimension('bnds', 2)

        # Time
        tvar = ds.createVariable('time', 'f8', ('time',))
        for attr in ['standard_name', 'long_name', 'units', 'calendar', 'axis']:
            setattr(tvar, attr, coord_specs['time'][attr])
        tvar.bounds = 'time_bnds'
        tvar[:] = new_time
        tb = ds.createVariable('time_bnds', 'f8', ('time', 'bnds'))
        tb[:] = time_bounds

        # Latitude
        lav = ds.createVariable('latitude', 'f8', ('latitude',))
        for attr in ['standard_name', 'long_name', 'units', 'axis']:
            setattr(lav, attr, coord_specs['latitude'][attr])
        lav.bounds = 'latitude_bnds'
        lav[:] = new_lat
        lab = ds.createVariable('latitude_bnds', 'f8', ('latitude', 'bnds'))
        lab[:] = lat_bnds

        # Longitude
        lov = ds.createVariable('longitude', 'f8', ('longitude',))
        for attr in ['standard_name', 'long_name', 'units', 'axis']:
            setattr(lov, attr, coord_specs['longitude'][attr])
        lov.bounds = 'longitude_bnds'
        lov[:] = new_lon
        lob = ds.createVariable('longitude_bnds', 'f8', ('longitude', 'bnds'))
        lob[:] = lon_bnds

        # Scalar coordinates
        if 'scalar_coordinates' in vspec:
            for cname, cspec in vspec['scalar_coordinates'].items():
                sc = ds.createVariable(cname, 'f8', ())
                sc[:] = cspec['value']
                for attr in ['standard_name', 'long_name', 'units', 'positive', 'axis']:
                    if attr in cspec:
                        setattr(sc, attr, cspec[attr])

        # Data variable
        dv = ds.createVariable(cmor_name, 'f4',
                               ('time', 'latitude', 'longitude'),
                               fill_value=np.float32(fill_val))
        dv.standard_name = vspec['standard_name']
        dv.long_name = vspec['long_name']
        dv.units = vspec['units']
        dv.cell_methods = vspec['cell_methods']
        if vspec.get('comment'):
            dv.comment = vspec['comment']
        dv[:] = data_f32

        # Global attributes
        for aname, aval in req_attrs.items():
            setattr(ds, aname, aval)
        ds.project_id = header['project_id']
        ds.dataset_id = header['dataset_id']
        ds.mip_table = header['mip_table']

        ds.close()
        print(f"  Written: {fpath}")

    raw.close()
    print("CMORization complete.")


if __name__ == '__main__':
    main()
