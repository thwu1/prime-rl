#!/usr/bin/env python3
"""Solve the CMIP6 multi-model climate sensitivity and extremes benchmark."""

import numpy as np
import xarray as xr
import json
import pandas as pd
from scipy.stats import linregress

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

catalog = pd.read_csv('/app/catalog.csv')
models = sorted(catalog['source_id'].unique())


def load_var(model, experiment, variable):
    row = catalog[(catalog['source_id'] == model) &
                  (catalog['experiment_id'] == experiment) &
                  (catalog['variable_id'] == variable)]
    if len(row) == 0:
        return None
    return xr.open_zarr(row.iloc[0]['zstore'], consolidated=True)[variable]


def to_K(da):
    if da.attrs.get('units', 'K') == 'degC':
        out = da + 273.15
        out.attrs = da.attrs.copy()
        out.attrs['units'] = 'K'
        return out
    return da


def to_C(da):
    if da.attrs.get('units', 'K') == 'K':
        out = da - 273.15
        out.attrs = da.attrs.copy()
        out.attrs['units'] = 'degC'
        return out
    return da


def awm(da):
    w = np.cos(np.deg2rad(da.lat))
    return da.weighted(w).mean(dim=['lat', 'lon'])


def stull_wbt(T, RH):
    return (T * np.arctan(0.151977 * np.sqrt(RH + 8.313659)) +
            np.arctan(T + RH) - np.arctan(RH - 1.676331) +
            0.00391838 * RH ** 1.5 * np.arctan(0.023101 * RH) - 4.686035)


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

results = {
    'ecs': {},
    'feedback_parameter': {},
    'forcing_2xCO2': {},
    'tcr': {},
    'ecs_tcr_ratio': {},
    'warming_ssp585_K': {},
    'max_wbt_C': {},
    'grid_cells_wbt_above_28': {},
}

for m in models:
    print(f"Processing {m} ...")

    # ---- Gregory regression: abrupt-4xCO2 vs piControl ----
    tas_pi = to_K(load_var(m, 'piControl', 'tas'))
    tas_4x = to_K(load_var(m, 'abrupt-4xCO2', 'tas'))
    rsdt = load_var(m, 'abrupt-4xCO2', 'rsdt')
    rsut = load_var(m, 'abrupt-4xCO2', 'rsut')
    rlut = load_var(m, 'abrupt-4xCO2', 'rlut')

    T_pi_mean = float(awm(tas_pi).mean(dim='time').values)
    T_4x_ann = awm(tas_4x).groupby('time.year').mean()
    dT = T_4x_ann.values - T_pi_mean

    N = rsdt - rsut - rlut
    N_ann = awm(N).groupby('time.year').mean()

    slope, intercept, _, _, _ = linregress(dT, N_ann.values)
    lam = float(slope)
    f4x = float(intercept)
    f2x = f4x / 2.0
    ecs = -f2x / lam

    results['feedback_parameter'][m] = round(lam, 4)
    results['forcing_2xCO2'][m] = round(f2x, 4)
    results['ecs'][m] = round(ecs, 4)
    print(f"  ECS={ecs:.3f} K, lambda={lam:.3f} W/m2/K, F_2x={f2x:.3f} W/m2")

    # ---- TCR from 1pctCO2 ----
    tas_1pct = load_var(m, '1pctCO2', 'tas')
    if tas_1pct is not None:
        tas_1pct_K = to_K(tas_1pct)
        T_1pct_ann = awm(tas_1pct_K).groupby('time.year').mean()
        dT_1pct = T_1pct_ann.values - T_pi_mean
        years = T_1pct_ann.year.values
        sim_yr = years - years[0]
        mask = (sim_yr >= 60) & (sim_yr <= 79)
        tcr = float(np.mean(dT_1pct[mask]))
        results['tcr'][m] = round(tcr, 4)
        results['ecs_tcr_ratio'][m] = round(ecs / tcr, 4)
        print(f"  TCR={tcr:.3f} K, ECS/TCR={ecs/tcr:.3f}")

    # ---- End-of-century warming ----
    tas_hist = to_K(load_var(m, 'historical', 'tas'))
    tas_ssp = to_K(load_var(m, 'ssp585', 'tas'))
    T_hist = float(awm(tas_hist).mean(dim='time').values)
    T_ssp = float(awm(tas_ssp.sel(time=slice('2091', '2100')))
                  .mean(dim='time').values)
    warming = T_ssp - T_hist
    results['warming_ssp585_K'][m] = round(warming, 4)
    print(f"  Warming = {warming:.3f} K")

    # ---- WBT extremes ----
    tas_raw = load_var(m, 'ssp585', 'tas')
    hurs = load_var(m, 'ssp585', 'hurs')
    T_C = to_C(tas_raw).sel(time=slice('2091', '2100'))
    RH = hurs.sel(time=slice('2091', '2100'))
    wbt = stull_wbt(T_C, RH)

    max_wbt = float(wbt.max().values)
    results['max_wbt_C'][m] = round(max_wbt, 4)

    wbt_tmean = wbt.mean(dim='time')
    n_cells = int((wbt_tmean > 28).sum().values)
    results['grid_cells_wbt_above_28'][m] = n_cells
    print(f"  Max WBT={max_wbt:.2f} C, cells>28={n_cells}")

# ---- Ensemble statistics ----
ecs_vals = list(results['ecs'].values())
results['ecs_ensemble_mean'] = round(float(np.mean(ecs_vals)), 4)
results['ecs_ensemble_std'] = round(float(np.std(ecs_vals, ddof=0)), 4)
results['models_outside_ipcc_likely'] = sorted(
    [m for m, v in results['ecs'].items() if v < 2.5 or v > 4.0])

# ---- Synthesis ----
ecs_sorted = sorted(results['ecs'].items(), key=lambda x: x[1], reverse=True)
results['ecs_ranking'] = [m for m, _ in ecs_sorted]
results['most_warming_model'] = max(
    results['warming_ssp585_K'].items(), key=lambda x: x[1])[0]

with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("\nResults written to /app/results.json")
print(f"ECS ranking: {results['ecs_ranking']}")
print(f"Most warming: {results['most_warming_model']}")
print(f"Models outside IPCC likely: {results['models_outside_ipcc_likely']}")
