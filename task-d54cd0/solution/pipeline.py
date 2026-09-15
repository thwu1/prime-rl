#!/usr/bin/env python3
"""CMIP6 climate extremes analysis: WBT conditional on ENSO phase."""

import numpy as np
import xarray as xr
import pandas as pd
import json
import os


def compute_wbt(T_celsius, RH_pct):
    """Stull (2011) wet bulb temperature approximation.

    Parameters
    ----------
    T_celsius : array-like, temperature in degrees Celsius
    RH_pct : array-like, relative humidity in percent (0-100)

    Returns
    -------
    Wet bulb temperature in degrees Celsius
    """
    return (
        T_celsius * np.arctan(0.151977 * np.sqrt(RH_pct + 8.313659))
        + np.arctan(T_celsius + RH_pct)
        - np.arctan(RH_pct - 1.676331)
        + 0.00391838 * RH_pct ** 1.5 * np.arctan(0.023101 * RH_pct)
        - 4.686035
    )


def compute_oni(tos_da):
    """Compute Oceanic Nino Index from sea surface temperature DataArray.

    Selects the Nino 3.4 region (5S-5N, 170W-120W = 190E-240E),
    computes area-weighted mean, removes monthly climatology,
    applies 3-month centered rolling mean.
    """
    # Nino 3.4: 5S-5N, 170W-120W  =>  190E-240E in 0-360 convention
    nino34 = tos_da.sel(lat=slice(-5, 5), lon=slice(190, 240))

    # Cosine-latitude area weighting
    weights = np.cos(np.deg2rad(nino34.lat))
    nino34_mean = nino34.weighted(weights).mean(dim=['lat', 'lon'])

    # Convert K to Celsius
    nino34_C = nino34_mean - 273.15

    # Monthly climatology
    climatology = nino34_C.groupby('time.month').mean()
    anomaly = nino34_C.groupby('time.month') - climatology

    # 3-month centered rolling mean
    oni = anomaly.rolling(time=3, center=True).mean()
    return oni


def main():
    # Read catalog to discover datasets
    catalog = pd.read_csv('/app/data/catalog.csv')

    # Filter to historical experiment, r1i1p1f1 member only
    hist = catalog[
        (catalog['experiment_id'] == 'historical') &
        (catalog['member_id'] == 'r1i1p1f1')
    ]

    models = sorted(hist['source_id'].unique())
    results = {'model_stats': {}, 'ensemble': {}}

    for model in models:
        model_cat = hist[hist['source_id'] == model]

        # Load zarr stores
        tas_path = model_cat[model_cat['variable_id'] == 'tas']['zstore'].values[0]
        hurs_path = model_cat[model_cat['variable_id'] == 'hurs']['zstore'].values[0]
        tos_path = model_cat[model_cat['variable_id'] == 'tos']['zstore'].values[0]

        ds_tas = xr.open_zarr(tas_path, consolidated=True)
        ds_hurs = xr.open_zarr(hurs_path, consolidated=True)
        ds_tos = xr.open_zarr(tos_path, consolidated=True)

        # --- Wet Bulb Temperature ---
        # tas is in K, convert to Celsius; hurs is in %
        T_celsius = ds_tas['tas'].values - 273.15
        RH = ds_hurs['hurs'].values
        wbt = compute_wbt(T_celsius, RH)

        # Spatial 90th percentile at each timestep
        nt = wbt.shape[0]
        wbt_flat = wbt.reshape(nt, -1)
        wbt_p90 = np.percentile(wbt_flat, 90, axis=1)

        # --- ENSO classification ---
        oni = compute_oni(ds_tos['tos'])
        oni_vals = oni.values

        valid = ~np.isnan(oni_vals)
        elnino = (oni_vals > 0.5) & valid
        lanina = (oni_vals < -0.5) & valid
        neutral = (~(oni_vals > 0.5)) & (~(oni_vals < -0.5)) & valid

        # Conditional statistics
        results['model_stats'][model] = {
            'wbt_p90_elnino_mean': float(np.mean(wbt_p90[elnino])),
            'wbt_p90_lanina_mean': float(np.mean(wbt_p90[lanina])),
            'wbt_p90_neutral_mean': float(np.mean(wbt_p90[neutral])),
            'elnino_month_count': int(np.sum(elnino)),
            'lanina_month_count': int(np.sum(lanina)),
        }

        print(f"{model}: El Nino={int(np.sum(elnino))} months, "
              f"La Nina={int(np.sum(lanina))} months, "
              f"WBT P90 El Nino={float(np.mean(wbt_p90[elnino])):.3f}, "
              f"La Nina={float(np.mean(wbt_p90[lanina])):.3f}, "
              f"Neutral={float(np.mean(wbt_p90[neutral])):.3f}")

    # --- Ensemble statistics ---
    for phase in ['elnino', 'lanina', 'neutral']:
        key = f'wbt_p90_{phase}_mean'
        vals = [results['model_stats'][m][key] for m in models]
        results['ensemble'][key] = float(np.mean(vals))
        results['ensemble'][f'wbt_p90_{phase}_std'] = float(np.std(vals, ddof=0))

    # Write output
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == '__main__':
    main()
