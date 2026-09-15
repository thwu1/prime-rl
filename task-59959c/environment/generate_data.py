#!/usr/bin/env python3
"""Generate synthetic CMIP6-like Zarr data for the analysis benchmark."""
import numpy as np
import xarray as xr
import json
import csv
import os

np.random.seed(42)

LONS = np.arange(5, 360, 10, dtype=np.float64)   # 36 points, 10-deg spacing
LATS = np.arange(-85, 90, 10, dtype=np.float64)   # 18 points, 10-deg spacing
NLON, NLAT = len(LONS), len(LATS)
DATA_DIR = '/app/data'
os.makedirs(DATA_DIR, exist_ok=True)

MODELS = {
    'SYNTH-ESM-A': {'ecs': 2.8, 'lam': -1.3,  'tau': 15.0, 'bt': 287.5,
                    'pct': True,  'unit': 'K'},
    'SYNTH-ESM-B': {'ecs': 3.6, 'lam': -1.1,  'tau': 20.0, 'bt': 288.0,
                    'pct': False, 'unit': 'K'},
    'SYNTH-ESM-C': {'ecs': 4.2, 'lam': -0.95, 'tau': 25.0, 'bt': 287.8,
                    'pct': True,  'unit': 'degC'},
    'SYNTH-ESM-D': {'ecs': 5.1, 'lam': -0.80, 'tau': 30.0, 'bt': 288.2,
                    'pct': False, 'unit': 'K'},
}

catalog = []


def monthly_time(y0, ny):
    return np.array(
        [np.datetime64(f'{y0+y}-{m+1:02d}-15') for y in range(ny) for m in range(12)],
        dtype='datetime64[ns]')


def base_field(bt):
    la, lo = np.meshgrid(LATS, LONS, indexing='ij')
    return bt + 25 * np.cos(np.deg2rad(la)) - 12 + 3 * np.sin(np.deg2rad(2 * lo))


def season(mi):
    la = np.meshgrid(LATS, LONS, indexing='ij')[0]
    return 5 * np.cos(2 * np.pi * (mi - 1) / 12) * np.sin(np.deg2rad(la))


# Polar amplification factor, normalised so area-weighted mean = 1
_la = np.meshgrid(LATS, LONS, indexing='ij')[0]
_raw = 0.7 + 0.4 * (1 - np.cos(np.deg2rad(_la)))
_wm = np.average(_raw[:, 0], weights=np.cos(np.deg2rad(LATS)))
PA = _raw / _wm


def save(path, vn, data, time, unit, eattrs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    da = xr.DataArray(data, dims=['time', 'lat', 'lon'],
                      coords={'time': time, 'lat': LATS, 'lon': LONS},
                      attrs={'units': unit}, name=vn)
    ds = xr.Dataset({vn: da}, attrs=eattrs)
    ds.lat.attrs = {'units': 'degrees_north', 'axis': 'Y'}
    ds.lon.attrs = {'units': 'degrees_east', 'axis': 'X'}
    ds.to_zarr(path, mode='w', consolidated=True)


def cat_row(mod, exp, var, path, act='CMIP'):
    catalog.append({
        'activity_id': act, 'institution_id': 'SYNTH',
        'source_id': mod, 'experiment_id': exp,
        'member_id': 'r1i1p1f1', 'table_id': 'Amon',
        'variable_id': var, 'grid_label': 'gn',
        'zstore': path, 'dcpp_init_year': '',
    })


for mn, p in MODELS.items():
    ecs, lam, tau, bt = p['ecs'], p['lam'], p['tau'], p['bt']
    has_pct, tu = p['pct'], p['unit']
    F2x = -lam * ecs
    F4x = 2 * F2x
    BF = base_field(bt)
    BF_s = (BF - 273.15) if tu == 'degC' else BF.copy()
    ea = {'source_id': mn, 'variant_label': 'r1i1p1f1'}

    # ---------- piControl: 30 yr (1850-1879) ----------
    t = monthly_time(1850, 30)
    d = np.stack([BF_s + season(i % 12) +
                  np.random.normal(0, 0.3, (NLAT, NLON)) for i in range(len(t))])
    path = f'{DATA_DIR}/{mn}/piControl/tas'
    save(path, 'tas', d, t, tu, {**ea, 'experiment_id': 'piControl'})
    cat_row(mn, 'piControl', 'tas', path)

    # ---------- abrupt-4xCO2: 50 yr (1850-1899) ----------
    t = monthly_time(1850, 50)
    nt = len(t)
    tas = np.zeros((nt, NLAT, NLON))
    rsdt = np.zeros_like(tas)
    rsut = np.zeros_like(tas)
    rlut = np.zeros_like(tas)
    for i in range(nt):
        yr = i / 12.0
        dTg = 2 * ecs * (1 - np.exp(-yr / tau))
        tas[i] = BF_s + dTg * PA + season(i % 12) + \
            np.random.normal(0, 0.3, (NLAT, NLON))
        Nv = F4x + lam * dTg + np.random.normal(0, 0.2)
        rsdt[i] = 340.0 + np.random.normal(0, 0.05, (NLAT, NLON))
        rsut[i] = 100.0 + np.random.normal(0, 0.05, (NLAT, NLON))
        rlut[i] = (240.0 - Nv) + np.random.normal(0, 0.05, (NLAT, NLON))
    for vn, dd, u in [('tas', tas, tu), ('rsdt', rsdt, 'W m-2'),
                       ('rsut', rsut, 'W m-2'), ('rlut', rlut, 'W m-2')]:
        path = f'{DATA_DIR}/{mn}/abrupt-4xCO2/{vn}'
        save(path, vn, dd, t, u, {**ea, 'experiment_id': 'abrupt-4xCO2'})
        cat_row(mn, 'abrupt-4xCO2', vn, path)

    # ---------- historical: 20 yr (1995-2014) ----------
    t = monthly_time(1995, 20)
    d = np.stack([BF_s + 0.02 * (i / 12.0) + season(i % 12) +
                  np.random.normal(0, 0.3, (NLAT, NLON)) for i in range(len(t))])
    path = f'{DATA_DIR}/{mn}/historical/tas'
    save(path, 'tas', d, t, tu, {**ea, 'experiment_id': 'historical'})
    cat_row(mn, 'historical', 'tas', path)

    # ---------- ssp585: 30 yr (2071-2100) ----------
    la_g = np.meshgrid(LATS, LONS, indexing='ij')[0]
    t = monthly_time(2071, 30)
    nt_s = len(t)
    tas_s = np.zeros((nt_s, NLAT, NLON))
    hurs_s = np.zeros((nt_s, NLAT, NLON))
    for i in range(nt_s):
        yr = i / 12.0
        wg = 0.5 + (ecs / 3.0) * (2.0 + 0.1 * yr)
        tas_s[i] = BF_s + wg * PA + season(i % 12) + \
            np.random.normal(0, 0.3, (NLAT, NLON))
        hurs_s[i] = np.clip(
            65 + 20 * np.cos(np.deg2rad(la_g)) +
            np.random.normal(0, 5, (NLAT, NLON)), 5, 100)
    for vn, dd, u in [('tas', tas_s, tu), ('hurs', hurs_s, '%')]:
        path = f'{DATA_DIR}/{mn}/ssp585/{vn}'
        save(path, vn, dd, t, u, {**ea, 'experiment_id': 'ssp585'})
        cat_row(mn, 'ssp585', vn, path, 'ScenarioMIP')

    # ---------- 1pctCO2: 80 yr (1850-1929) — select models only ----------
    if has_pct:
        t = monthly_time(1850, 80)
        d = np.zeros((len(t), NLAT, NLON))
        for i in range(len(t)):
            yr = i / 12.0
            dTg = (ecs / 69.66) * (yr - tau * (1 - np.exp(-yr / tau)))
            d[i] = BF_s + dTg * PA + season(i % 12) + \
                np.random.normal(0, 0.3, (NLAT, NLON))
        path = f'{DATA_DIR}/{mn}/1pctCO2/tas'
        save(path, 'tas', d, t, tu, {**ea, 'experiment_id': '1pctCO2'})
        cat_row(mn, '1pctCO2', 'tas', path)

# ---------- Write catalog ----------
fns = ['activity_id', 'institution_id', 'source_id', 'experiment_id',
       'member_id', 'table_id', 'variable_id', 'grid_label',
       'zstore', 'dcpp_init_year']
with open('/app/catalog.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fns)
    w.writeheader()
    w.writerows(catalog)

spec = {
    "esmcat_version": "0.1.0",
    "id": "synthetic_cmip6",
    "description": "Synthetic CMIP6 data for analysis benchmark",
    "catalog_file": "/app/catalog.csv",
    "attributes": [{"column_name": c, "vocabulary": ""}
                    for c in fns if c not in ('zstore', 'dcpp_init_year')],
    "assets": {"column_name": "zstore", "format": "zarr"},
    "aggregation_control": {
        "variable_column_name": "variable_id",
        "groupby_attrs": ["activity_id", "institution_id", "source_id",
                          "experiment_id", "member_id", "table_id",
                          "grid_label"],
        "aggregations": [{"type": "union", "attribute_name": "variable_id"}]
    }
}
with open('/app/catalog.json', 'w') as f:
    json.dump(spec, f, indent=2)

print(f"Generated data for {len(MODELS)} models, {len(catalog)} catalog entries")
