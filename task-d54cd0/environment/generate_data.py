#!/usr/bin/env python3
"""Generate synthetic CMIP6-structured Zarr stores and intake-esm catalog."""

import numpy as np
import xarray as xr
import pandas as pd
import os
import json
import csv


def main():
    # Grid: 5-degree resolution
    lats = np.arange(-87.5, 90, 5.0)   # 36 points
    lons = np.arange(2.5, 360, 5.0)    # 72 points
    nlat, nlon = len(lats), len(lons)

    # Time: monthly 1950-01 to 2014-12
    times = pd.date_range('1950-01-01', '2014-12-31', freq='MS')
    nt = len(times)  # 780

    models = ['ModelAlpha', 'ModelBeta', 'ModelGamma']

    # Shared ENSO-like quasi-periodic oscillation
    t_idx = np.arange(nt, dtype=np.float64)
    enso_base = (
        0.8 * np.sin(2 * np.pi * t_idx / 42)
        + 0.6 * np.sin(2 * np.pi * t_idx / 60)
        + 0.4 * np.sin(2 * np.pi * t_idx / 28)
        + 0.3 * np.cos(2 * np.pi * t_idx / 84)
    )

    base_dir = '/app/data/zarr_stores'
    catalog_rows = []
    month_arr = np.array([t.month for t in times])
    month_frac = (month_arr - 1) / 12.0
    month_frac_h = (month_arr - 7) / 12.0

    for mi, model in enumerate(models):
        rng = np.random.RandomState(42 + mi * 100)
        model_enso = enso_base + 0.15 * rng.randn(nt)

        store_base = os.path.join(base_dir, model, 'historical', 'r1i1p1f1')
        os.makedirs(store_base, exist_ok=True)

        # === TAS: near-surface air temperature (K) ===
        lat_base_tas = 288.0 - 40.0 * (lats / 90.0) ** 2
        seasonal_amp_tas = 15.0 * np.abs(lats / 90.0)
        trend_tas = 0.015 * t_idx / 12.0
        enso_tele = model_enso[:, None] * 0.5 * np.exp(-(lats[None, :] / 30.0) ** 2)
        seasonal_tas = seasonal_amp_tas[None, :] * np.cos(2 * np.pi * month_frac[:, None])

        tas_2d = lat_base_tas[None, :] + seasonal_tas + trend_tas[:, None] + enso_tele
        tas_data = (tas_2d[:, :, None] + 0.3 * rng.randn(nt, nlat, nlon)).astype(np.float32)

        ds_tas = xr.Dataset({
            'tas': xr.DataArray(
                tas_data, dims=['time', 'lat', 'lon'],
                coords={'time': times, 'lat': lats, 'lon': lons},
                attrs={'units': 'K', 'long_name': 'Near-Surface Air Temperature',
                       'standard_name': 'air_temperature'}
            )
        }, attrs={'source_id': model, 'experiment_id': 'historical',
                  'variant_label': 'r1i1p1f1', 'grid_label': 'gn',
                  'Conventions': 'CF-1.7 CMIP-6.2'})

        tas_path = os.path.join(store_base, 'tas')
        ds_tas.to_zarr(tas_path, mode='w', consolidated=True)
        catalog_rows.append({
            'source_id': model, 'experiment_id': 'historical',
            'variable_id': 'tas', 'member_id': 'r1i1p1f1',
            'grid_label': 'gn', 'table_id': 'Amon',
            'zstore': tas_path
        })

        # === HURS: near-surface relative humidity (%) ===
        lat_base_hurs = 70.0 - 20.0 * (np.abs(lats) / 90.0)
        seasonal_hurs = 8.0 * np.cos(2 * np.pi * month_frac_h[:, None]) * (np.abs(lats[None, :]) / 90.0)
        hurs_2d = lat_base_hurs[None, :] + seasonal_hurs
        hurs_data = (hurs_2d[:, :, None] + 2.0 * rng.randn(nt, nlat, nlon)).astype(np.float32)
        hurs_data = np.clip(hurs_data, 5.0, 100.0)

        ds_hurs = xr.Dataset({
            'hurs': xr.DataArray(
                hurs_data, dims=['time', 'lat', 'lon'],
                coords={'time': times, 'lat': lats, 'lon': lons},
                attrs={'units': '%', 'long_name': 'Near-Surface Relative Humidity',
                       'standard_name': 'relative_humidity'}
            )
        }, attrs={'source_id': model, 'experiment_id': 'historical',
                  'variant_label': 'r1i1p1f1', 'grid_label': 'gn',
                  'Conventions': 'CF-1.7 CMIP-6.2'})

        hurs_path = os.path.join(store_base, 'hurs')
        ds_hurs.to_zarr(hurs_path, mode='w', consolidated=True)
        catalog_rows.append({
            'source_id': model, 'experiment_id': 'historical',
            'variable_id': 'hurs', 'member_id': 'r1i1p1f1',
            'grid_label': 'gn', 'table_id': 'Amon',
            'zstore': hurs_path
        })

        # === TOS: sea surface temperature (K) ===
        lat_base_tos = 298.0 - 30.0 * (lats / 90.0) ** 2
        seasonal_tos = 2.0 * np.cos(2 * np.pi * month_frac[:, None]) * (np.abs(lats[None, :]) / 90.0)
        # ENSO signal concentrated in Nino 3.4 region via Gaussian envelope
        nino_lat = np.exp(-(lats / 5.0) ** 2)
        nino_lon = np.exp(-((lons - 215.0) / 25.0) ** 2)
        enso_spatial = model_enso[:, None, None] * nino_lat[None, :, None] * nino_lon[None, None, :]

        tos_base = (lat_base_tos[None, :] + seasonal_tos)[:, :, None]
        tos_data = (tos_base + enso_spatial + 0.2 * rng.randn(nt, nlat, nlon)).astype(np.float32)

        ds_tos = xr.Dataset({
            'tos': xr.DataArray(
                tos_data, dims=['time', 'lat', 'lon'],
                coords={'time': times, 'lat': lats, 'lon': lons},
                attrs={'units': 'K', 'long_name': 'Sea Surface Temperature',
                       'standard_name': 'sea_surface_temperature'}
            )
        }, attrs={'source_id': model, 'experiment_id': 'historical',
                  'variant_label': 'r1i1p1f1', 'grid_label': 'gn',
                  'Conventions': 'CF-1.7 CMIP-6.2'})

        tos_path = os.path.join(store_base, 'tos')
        ds_tos.to_zarr(tos_path, mode='w', consolidated=True)
        catalog_rows.append({
            'source_id': model, 'experiment_id': 'historical',
            'variable_id': 'tos', 'member_id': 'r1i1p1f1',
            'grid_label': 'gn', 'table_id': 'Omon',
            'zstore': tos_path
        })

    # --- intake-esm catalog ---
    os.makedirs('/app/data', exist_ok=True)

    catalog_spec = {
        "esmcat_version": "0.1.0",
        "id": "cmip6_synthetic",
        "description": "Synthetic CMIP6-like dataset catalog for climate analysis",
        "catalog_file": "/app/data/catalog.csv",
        "attributes": [
            {"column_name": "source_id", "vocabulary": ""},
            {"column_name": "experiment_id", "vocabulary": ""},
            {"column_name": "variable_id", "vocabulary": ""},
            {"column_name": "member_id", "vocabulary": ""},
            {"column_name": "grid_label", "vocabulary": ""},
            {"column_name": "table_id", "vocabulary": ""}
        ],
        "assets": {
            "column_name": "zstore",
            "format": "zarr"
        },
        "aggregation_control": {
            "variable_column_name": "variable_id",
            "groupby_attrs": [
                "source_id", "experiment_id", "member_id",
                "grid_label", "table_id"
            ],
            "aggregations": [
                {"type": "union", "attribute_name": "variable_id"}
            ]
        }
    }

    with open('/app/data/catalog.json', 'w') as f:
        json.dump(catalog_spec, f, indent=2)

    fieldnames = ['source_id', 'experiment_id', 'variable_id',
                  'member_id', 'grid_label', 'table_id', 'zstore']

    # Add distractor rows (non-existent future scenarios to test filtering)
    distractors = [
        {'source_id': 'ModelAlpha', 'experiment_id': 'ssp585',
         'variable_id': 'tas', 'member_id': 'r1i1p1f1',
         'grid_label': 'gn', 'table_id': 'Amon',
         'zstore': '/app/data/zarr_stores/ModelAlpha/ssp585/r1i1p1f1/tas'},
        {'source_id': 'ModelBeta', 'experiment_id': 'historical',
         'variable_id': 'tas', 'member_id': 'r2i1p1f1',
         'grid_label': 'gn', 'table_id': 'Amon',
         'zstore': '/app/data/zarr_stores/ModelBeta/historical/r2i1p1f1/tas'},
        {'source_id': 'ModelGamma', 'experiment_id': 'ssp245',
         'variable_id': 'hurs', 'member_id': 'r1i1p1f1',
         'grid_label': 'gn', 'table_id': 'Amon',
         'zstore': '/app/data/zarr_stores/ModelGamma/ssp245/r1i1p1f1/hurs'},
    ]

    with open('/app/data/catalog.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(catalog_rows + distractors)

    print(f"Generated {len(catalog_rows)} real + {len(distractors)} distractor catalog entries")


if __name__ == '__main__':
    main()
