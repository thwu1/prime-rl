#!/usr/bin/env python3
"""Generate synthetic CMIP6-like climate model output for the pipeline task."""
import numpy as np
import json
import os

nlat, nlon, ntime = 36, 72, 120
lats = np.linspace(-87.5, 87.5, nlat)
lons = np.linspace(0, 355, nlon)

lat_rad = np.deg2rad(lats)
lon_rad = np.deg2rad(lons)

lat_mesh, lon_mesh = np.meshgrid(lat_rad, lon_rad, indexing="ij")
lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")

month_of_year = np.arange(ntime) % 12
month_frac = month_of_year / 12.0

# Shared masks
ocean_mask = np.ones((nlat, nlon), dtype=bool)
ocean_mask &= ~((lon_grid >= 20) & (lon_grid <= 50) & (lat_grid >= -35) & (lat_grid <= 35))
ocean_mask &= ~((lon_grid >= 260) & (lon_grid <= 290) & (lat_grid >= -55) & (lat_grid <= 55))
ocean_mask &= ~((lon_grid >= 70) & (lon_grid <= 130) & (lat_grid >= 10) & (lat_grid <= 55))
ocean_mask &= (np.abs(lat_grid) <= 62.5)

nino34_mask = ((lat_grid >= -5) & (lat_grid <= 5) &
               (lon_grid >= 190) & (lon_grid <= 240))

models = {
    "MODEL-A": {"tas_unit": "K", "hurs_unit": "%",
                "phase": 0.0, "tas_bias": 0.0, "seed": 100, "sst_trend": 0.20},
    "MODEL-B": {"tas_unit": "degC", "hurs_unit": "%",
                "phase": float(np.pi / 3), "tas_bias": 1.5, "seed": 200, "sst_trend": 0.35},
    "MODEL-C": {"tas_unit": "K", "hurs_unit": "1",
                "phase": float(2 * np.pi / 3), "tas_bias": -0.8, "seed": 300, "sst_trend": 0.15},
}

base_dir = "/data/raw_data"
os.makedirs(base_dir, exist_ok=True)

for model_name, params in models.items():
    rng = np.random.RandomState(params["seed"])
    model_dir = os.path.join(base_dir, model_name)
    os.makedirs(model_dir, exist_ok=True)

    # --- TAS (near-surface air temperature) ---
    spatial_base = 288.0 + 20.0 * np.cos(lat_mesh)
    seasonal = (-15.0 * np.cos(2 * np.pi * month_frac)[:, None, None]
                * np.cos(lat_mesh)[None, :, :])
    lon_var = 2.0 * np.sin(lon_mesh + params["phase"])
    tas_K = (spatial_base[None, :, :] + seasonal
             + lon_var[None, :, :] + params["tas_bias"])
    tas_K += rng.normal(0, 0.5, tas_K.shape)

    if params["tas_unit"] == "degC":
        tas_save = tas_K - 273.15
    else:
        tas_save = tas_K.copy()

    # --- HURS (near-surface relative humidity) ---
    hurs_base = 60.0 + 20.0 * np.cos(lat_mesh)
    hurs_seasonal = 10.0 * np.sin(2 * np.pi * month_frac)[:, None, None]
    hurs_pct = (hurs_base[None, :, :] + hurs_seasonal
                + rng.normal(0, 3.0, (ntime, nlat, nlon)))
    hurs_pct = np.clip(hurs_pct, 5.0, 100.0)

    if params["hurs_unit"] == "1":
        hurs_save = hurs_pct / 100.0
    else:
        hurs_save = hurs_pct.copy()

    # --- TOS (sea surface temperature) ---
    sst_base = 300.0 + 3.0 * np.cos(lat_mesh)
    sst_seasonal = (-2.0 * np.cos(2 * np.pi * month_frac)[:, None, None]
                    * np.cos(lat_mesh)[None, :, :])
    sst_field = sst_base[None, :, :] + sst_seasonal

    # Warming trend (K/decade, applied over 120 months = 1 decade)
    warming = params["sst_trend"] * (np.arange(ntime) / 120.0)[:, None, None]
    sst_field = sst_field + warming

    # ENSO signal in Nino 3.4 region
    enso_signal = 1.5 * np.sin(
        2 * np.pi * np.arange(ntime) / 48.0 + params["phase"])
    enso_3d = enso_signal[:, None, None] * nino34_mask[None, :, :].astype(float)
    sst_field = sst_field + enso_3d

    # Apply ocean mask and add noise
    tos_K = np.where(ocean_mask[None, :, :], sst_field, np.nan)
    noise = rng.normal(0, 0.3, tos_K.shape)
    tos_K = np.where(np.isnan(tos_K), np.nan, tos_K + noise)

    # Save arrays
    np.save(os.path.join(model_dir, "tas.npy"), tas_save.astype(np.float64))
    np.save(os.path.join(model_dir, "hurs.npy"), hurs_save.astype(np.float64))
    np.save(os.path.join(model_dir, "tos.npy"), tos_K.astype(np.float64))

    # Save metadata
    metadata = {
        "source_id": model_name,
        "experiment_id": "historical",
        "member_id": "r1i1p1f1",
        "grid_label": "gn",
        "frequency": "mon",
        "variables": {
            "tas": {
                "units": params["tas_unit"],
                "long_name": "Near-Surface Air Temperature",
                "standard_name": "air_temperature"
            },
            "hurs": {
                "units": params["hurs_unit"],
                "long_name": "Near-Surface Relative Humidity",
                "standard_name": "relative_humidity"
            },
            "tos": {
                "units": "K",
                "long_name": "Sea Surface Temperature",
                "standard_name": "sea_surface_temperature"
            },
        },
        "dimensions": {
            "time": {
                "size": ntime,
                "start_year": 2000,
                "start_month": 1,
                "frequency": "monthly"
            },
            "lat": {
                "size": nlat,
                "values": lats.tolist()
            },
            "lon": {
                "size": nlon,
                "values": lons.tolist()
            },
        }
    }

    with open(os.path.join(model_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

print("Synthetic CMIP6 data generated successfully.")
