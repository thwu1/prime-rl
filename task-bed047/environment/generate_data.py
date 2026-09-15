#!/usr/bin/env python3
"""Generate synthetic CMIP6-like climate data with realistic quality issues.
No zarr library dependency needed at build time -- writes raw zarr v2 format."""

import numpy as np
import json
import os
import math

# ---- Grid ----
nlat, nlon = 18, 36
lat = np.linspace(-85, 85, nlat)
lon_standard = np.linspace(-175, 175, nlon)   # standard convention
lon_360 = np.linspace(5, 355, nlon)           # 0-360 convention

N_YEARS = 30
N_MONTHS = N_YEARS * 12  # 360
HIST_START = 1980
SSP_START = 2071
SSP_WARMING = 4.5  # degC warming in ssp585

# ---- Model configurations ----
MODELS = ['CESM2', 'GFDL', 'UKESM', 'MIROC']
MODEL_CONFIG = {
    'CESM2': {
        'sensitivity': 1.0, 'bias': 0.8, 'seed': 2000,
        'tas_store_unit': 'K', 'tas_label_unit': 'K',       # correct metadata
        'hurs_unit': '%', 'lon_type': 'standard',
        'consolidate': True, 'chunks': (12, 18, 36),
        'inject_nan': False,
    },
    'GFDL': {
        'sensitivity': 0.9, 'bias': 0.0, 'seed': 3000,
        'tas_store_unit': 'degC', 'tas_label_unit': 'K',    # METADATA LIE: says K, actually degC
        'hurs_unit': '%', 'lon_type': 'standard',
        'consolidate': True, 'chunks': (36, 9, 18),
        'inject_nan': False,
    },
    'UKESM': {
        'sensitivity': 1.2, 'bias': -0.5, 'seed': 4000,
        'tas_store_unit': 'degC', 'tas_label_unit': 'degC',  # correct metadata
        'hurs_unit': '1', 'lon_type': '360',                 # 0-360 longitude, humidity as fraction
        'consolidate': False,                                  # no consolidated metadata
        'chunks': (12, 9, 36),
        'inject_nan': False,
    },
    'MIROC': {
        'sensitivity': 1.1, 'bias': -2.5, 'seed': 5000,
        'tas_store_unit': 'K', 'tas_label_unit': 'K',        # correct metadata
        'hurs_unit': '%', 'lon_type': 'standard',
        'consolidate': True, 'chunks': (12, 18, 36),
        'inject_nan': True,                                    # NaN block in historical
    },
}

REF_SEED = 1000


def generate_temp_field(bias, warming_offset, seed, lon_arr):
    """Generate monthly temperature in degC with continental pattern."""
    rng = np.random.RandomState(seed)
    lat_grid = np.broadcast_to(lat[:, None], (nlat, nlon))
    lon_grid = np.broadcast_to(lon_arr[None, :], (nlat, nlon))

    # Base pattern: warm tropics, cold poles, plus continental asymmetry
    base_temp = 30.0 - 0.5 * np.abs(lat_grid) + 1.5 * np.cos(np.deg2rad(lon_grid))

    seasonal_amp = 10.0 * np.abs(lat[:, None]) / 90.0
    seasonal = np.stack([
        seasonal_amp * np.cos(2 * np.pi * (m % 12 - 6) / 12.0)
        for m in range(N_MONTHS)
    ])
    noise = rng.randn(N_MONTHS, nlat, nlon) * 2.0
    return (base_temp[None, :, :] + seasonal + bias + warming_offset + noise).astype(np.float32)


def generate_hum_field(warming_offset, seed):
    """Generate monthly relative humidity in percent."""
    rng = np.random.RandomState(seed + 10000)
    lat_grid = np.broadcast_to(lat[:, None], (nlat, nlon))
    base_hum = 70.0 - 0.3 * np.abs(lat_grid)
    seasonal_h = np.stack([
        (5.0 * np.abs(lat[:, None]) / 90.0) * np.cos(2 * np.pi * (m % 12 - 3) / 12.0)
        for m in range(N_MONTHS)
    ])
    noise = rng.randn(N_MONTHS, nlat, nlon) * 5.0
    hum_pct = (base_hum[None, :, :] + seasonal_h - 2.0 * warming_offset + noise).astype(np.float32)
    return np.clip(hum_pct, 5.0, 100.0)


# ---- Zarr v2 raw writer (no zarr library needed) ----

def write_zarr_array(store_path, name, data, chunks, dtype_str, attrs):
    arr_path = os.path.join(store_path, name)
    os.makedirs(arr_path, exist_ok=True)
    shape = data.shape
    zarray = {
        "chunks": list(chunks),
        "compressor": None,
        "dtype": dtype_str,
        "fill_value": 0.0,
        "filters": None,
        "order": "C",
        "shape": list(shape),
        "zarr_format": 2
    }
    with open(os.path.join(arr_path, ".zarray"), "w") as f:
        json.dump(zarray, f)
    with open(os.path.join(arr_path, ".zattrs"), "w") as f:
        json.dump(attrs, f)

    dt = np.dtype(dtype_str)
    n_chunks_per_dim = [math.ceil(s / c) for s, c in zip(shape, chunks)]
    for idx in np.ndindex(*n_chunks_per_dim):
        slices = tuple(
            slice(i * c, min((i + 1) * c, s))
            for i, c, s in zip(idx, chunks, shape)
        )
        chunk_data = np.ascontiguousarray(data[slices]).astype(dt)
        if chunk_data.shape != tuple(chunks):
            padded = np.zeros(chunks, dtype=dt)
            inner = tuple(slice(0, s) for s in chunk_data.shape)
            padded[inner] = chunk_data
            chunk_data = padded
        chunk_name = ".".join(str(i) for i in idx)
        with open(os.path.join(arr_path, chunk_name), "wb") as f:
            f.write(chunk_data.tobytes(order="C"))
    return zarray, attrs


def write_zarr_store(store_path, datasets, group_attrs, consolidate):
    os.makedirs(store_path, exist_ok=True)
    zgroup = {"zarr_format": 2}
    with open(os.path.join(store_path, ".zgroup"), "w") as f:
        json.dump(zgroup, f)
    with open(os.path.join(store_path, ".zattrs"), "w") as f:
        json.dump(group_attrs, f)

    all_meta = {}
    for name, (data, chunks, dtype_str, attrs) in datasets.items():
        zarray, zattrs = write_zarr_array(store_path, name, data, chunks, dtype_str, attrs)
        all_meta[name + "/.zarray"] = zarray
        all_meta[name + "/.zattrs"] = zattrs

    if consolidate:
        zmetadata = {
            "metadata": {
                ".zattrs": group_attrs,
                ".zgroup": zgroup,
            },
            "zarr_consolidated_format": 1
        }
        zmetadata["metadata"].update(all_meta)
        with open(os.path.join(store_path, ".zmetadata"), "w") as f:
            json.dump(zmetadata, f)


# ---- Generate reference dataset (reanalysis) ----
ref_temp = generate_temp_field(0.0, 0.0, REF_SEED, lon_standard)
ref_hum = generate_hum_field(0.0, REF_SEED)
store_path = '/app/data/reference/historical'
datasets = {
    'tas': (ref_temp, (12, 18, 36), '<f4',
            {'units': 'degC', 'long_name': 'Near-Surface Air Temperature'}),
    'hurs': (ref_hum, (12, 18, 36), '<f4',
             {'units': '%', 'long_name': 'Near-Surface Relative Humidity'}),
    'lat': (lat, (nlat,), '<f8', {'units': 'degrees_north'}),
    'lon': (lon_standard, (nlon,), '<f8', {'units': 'degrees_east'}),
    'time': (np.arange(N_MONTHS, dtype='float64'), (N_MONTHS,), '<f8',
             {'units': 'months since {}-01-01'.format(HIST_START), 'start_year': HIST_START}),
}
write_zarr_store(store_path, datasets,
                 {'source_id': 'reanalysis', 'experiment_id': 'historical'}, True)

# ---- Generate model datasets ----
for model in MODELS:
    cfg = MODEL_CONFIG[model]
    lon_arr = lon_360 if cfg['lon_type'] == '360' else lon_standard

    for exp in ['historical', 'ssp585']:
        start_year = HIST_START if exp == 'historical' else SSP_START
        warming = 0.0 if exp == 'historical' else SSP_WARMING * cfg['sensitivity']
        seed = cfg['seed'] if exp == 'historical' else cfg['seed'] + 1

        temp_c = generate_temp_field(cfg['bias'], warming, seed, lon_arr)
        hum_pct = generate_hum_field(warming, seed)

        # Inject NaN block for MIROC historical (months 150-161 = 12 months)
        if cfg['inject_nan'] and exp == 'historical':
            temp_c[150:162] = np.nan
            hum_pct[150:162] = np.nan

        # Convert temperature to storage unit
        if cfg['tas_store_unit'] == 'K':
            tas_data = temp_c + 273.15
        else:
            tas_data = temp_c.copy()

        # Convert humidity to storage unit
        if cfg['hurs_unit'] == '1':
            hurs_data = hum_pct / 100.0
        else:
            hurs_data = hum_pct.copy()

        store_path = '/app/data/{}/{}'.format(model, exp)
        time_vals = np.arange(N_MONTHS, dtype='float64')

        datasets = {
            'tas': (tas_data, cfg['chunks'], '<f4', {
                'units': cfg['tas_label_unit'],
                'long_name': 'Near-Surface Air Temperature',
            }),
            'hurs': (hurs_data, cfg['chunks'], '<f4', {
                'units': cfg['hurs_unit'],
                'long_name': 'Near-Surface Relative Humidity',
            }),
            'lat': (lat, (nlat,), '<f8', {'units': 'degrees_north'}),
            'lon': (lon_arr, (nlon,), '<f8', {'units': 'degrees_east'}),
            'time': (time_vals, (N_MONTHS,), '<f8', {
                'units': 'months since {}-01-01'.format(start_year),
                'start_year': start_year,
            }),
        }

        write_zarr_store(store_path, datasets,
                         {'source_id': model, 'experiment_id': exp, 'frequency': 'mon'},
                         cfg['consolidate'])

# ---- Write catalog ----
catalog = {'reference': {'historical': '/app/data/reference/historical'}}
for m in MODELS:
    catalog[m] = {
        'historical': '/app/data/{}/historical'.format(m),
        'ssp585': '/app/data/{}/ssp585'.format(m),
    }

with open('/app/data/catalog.json', 'w') as f:
    json.dump(catalog, f, indent=2)

print("Data generation complete.")
