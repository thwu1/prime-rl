#!/usr/bin/env python3
"""Solution pipeline: raw numpy CMIP6 data -> Zarr stores + catalog + analysis."""

import json
import os

import numpy as np
import pandas as pd
import xarray as xr
import zarr
from numcodecs import Blosc

RAW_DIR = "/data/raw_data"
ZARR_DIR = "/app/zarr_stores"
MODELS = ["MODEL-A", "MODEL-B", "MODEL-C"]
VARS = ["tas", "hurs", "tos"]

# Standard units after normalisation
STANDARD_UNITS = {"tas": "K", "hurs": "%", "tos": "K"}

# -----------------------------------------------------------------------
# 1. Read raw data, normalise, and write Zarr stores
# -----------------------------------------------------------------------
normalised = {}  # model -> {var: ndarray, lats, lons}

for model in MODELS:
    mdir = os.path.join(RAW_DIR, model)
    with open(os.path.join(mdir, "metadata.json")) as fh:
        meta = json.load(fh)

    lats = np.array(meta["dimensions"]["lat"]["values"])
    lons = np.array(meta["dimensions"]["lon"]["values"])
    ntime = meta["dimensions"]["time"]["size"]
    times = pd.date_range(
        f"{meta['dimensions']['time']['start_year']}-"
        f"{meta['dimensions']['time']['start_month']:02d}-01",
        periods=ntime, freq="MS")

    arrays = {}
    for var in VARS:
        raw = np.load(os.path.join(mdir, f"{var}.npy"))
        unit = meta["variables"][var]["units"]

        # Normalise
        if var == "tas":
            data = raw + 273.15 if unit == "degC" else raw.copy()
        elif var == "hurs":
            data = raw * 100.0 if unit == "1" else raw.copy()
        else:
            data = raw.copy()

        arrays[var] = data

        # Build xarray Dataset
        ds = xr.Dataset({
            var: xr.DataArray(
                data,
                dims=["time", "lat", "lon"],
                coords={"time": times, "lat": lats, "lon": lons},
                attrs={
                    "units": STANDARD_UNITS[var],
                    "long_name": meta["variables"][var]["long_name"],
                    "standard_name": meta["variables"][var]["standard_name"],
                },
            )
        })

        store_path = os.path.join(ZARR_DIR, model, var)
        os.makedirs(os.path.dirname(store_path), exist_ok=True)

        encoding = {
            var: {
                "chunks": (12, len(lats), len(lons)),
                "compressor": Blosc(cname="zstd", clevel=3),
            }
        }
        ds.to_zarr(store_path, mode="w", encoding=encoding, consolidated=True)

    normalised[model] = {"lats": lats, "lons": lons, **arrays}

print("Zarr stores written.")

# -----------------------------------------------------------------------
# 2. Create ESM catalog
# -----------------------------------------------------------------------
catalog_desc = {
    "esmcat_version": "0.1.0",
    "id": "cmip6_local_zarr",
    "description": "Local CMIP6-like Zarr store catalog",
    "catalog_file": "/app/catalog.csv",
    "attributes": [
        {"column_name": "source_id"},
        {"column_name": "experiment_id"},
        {"column_name": "variable_id"},
        {"column_name": "member_id"},
    ],
    "assets": {
        "column_name": "zstore",
        "format": "zarr",
    },
}

with open("/app/catalog.json", "w") as fh:
    json.dump(catalog_desc, fh, indent=2)

rows = ["source_id,experiment_id,variable_id,member_id,zstore"]
for model in MODELS:
    for var in VARS:
        rows.append(f"{model},historical,{var},r1i1p1f1,"
                    f"/app/zarr_stores/{model}/{var}")

with open("/app/catalog.csv", "w") as fh:
    fh.write("\n".join(rows) + "\n")

print("Catalog written.")

# -----------------------------------------------------------------------
# 3. Compute analysis results
# -----------------------------------------------------------------------

def stull_wbt(T_celsius, RH_percent):
    """Stull (2011) wet-bulb temperature approximation (degrees C)."""
    T = T_celsius
    RH = RH_percent
    return (T * np.arctan(0.151977 * np.sqrt(RH + 8.313659))
            + np.arctan(T + RH)
            - np.arctan(RH - 1.676331)
            + 0.00391838 * np.power(RH, 1.5) * np.arctan(0.023101 * RH)
            - 4.686035)


wbt_raw_means = {}
oni_pos_counts = []
oni_neg_counts = []
enso_amp_list = []
heat_stress_frac_list = []
sst_trend_list = []

for model in MODELS:
    d = normalised[model]
    lats = d["lats"]
    lons = d["lons"]
    ntime = d["tas"].shape[0]
    nlat = len(lats)
    nlon = len(lons)

    # ---- WBT ----
    T_C = d["tas"] - 273.15
    RH = d["hurs"]
    wbt = stull_wbt(T_C, RH)

    cos_w = np.cos(np.deg2rad(lats))
    wbt_lon_mean = np.nanmean(wbt, axis=2)                       # (ntime, nlat)
    wbt_global = np.average(wbt_lon_mean, weights=cos_w, axis=1)  # (ntime,)
    wbt_raw_means[model] = float(np.mean(wbt_global))

    # ---- Tropical heat stress ----
    tropical_mask = np.abs(lats) <= 23.5
    wbt_tropical = wbt[:, tropical_mask, :]
    n_total = wbt_tropical.size
    n_exceed = int(np.sum(wbt_tropical > 28.0))
    heat_stress_frac_list.append(float(n_exceed) / float(n_total))

    # ---- ONI ----
    lat_sel = (lats >= -5) & (lats <= 5)
    lon_sel = (lons >= 190) & (lons <= 240)
    nino34 = d["tos"][:, lat_sel, :][:, :, lon_sel]
    nino_w = np.cos(np.deg2rad(lats[lat_sel]))

    nino_mean = np.zeros(ntime)
    for t in range(ntime):
        fld = nino34[t]
        w2d = np.broadcast_to(nino_w[:, None], fld.shape)
        nino_mean[t] = np.average(fld, weights=w2d)

    clim = np.array([np.mean(nino_mean[m::12]) for m in range(12)])
    anom = np.array([nino_mean[t] - clim[t % 12] for t in range(ntime)])
    rolling = np.convolve(anom, np.ones(3) / 3, mode="valid")

    oni_pos_counts.append(int(np.sum(rolling > 0.5)))
    oni_neg_counts.append(int(np.sum(rolling < -0.5)))
    enso_amp_list.append(float(np.std(rolling, ddof=0)))

    # ---- SST global trend ----
    lat_weights_2d = np.broadcast_to(cos_w[:, None], (nlat, nlon))
    sst_ts = np.zeros(ntime)
    for t in range(ntime):
        field = d["tos"][t]
        valid = ~np.isnan(field)
        sst_ts[t] = np.average(field[valid], weights=lat_weights_2d[valid])

    t_months = np.arange(ntime, dtype=float)
    coeffs = np.polyfit(t_months, sst_ts, 1)
    slope_per_month = coeffs[0]
    trend_per_decade = slope_per_month * 120.0
    sst_trend_list.append(float(trend_per_decade))

vals = list(wbt_raw_means.values())
results = {
    "wbt_global_mean": round(float(np.mean(vals)), 4),
    "wbt_model_means": {k: round(v, 4) for k, v in wbt_raw_means.items()},
    "oni_positive_months": round(float(np.mean(oni_pos_counts)), 4),
    "oni_negative_months": round(float(np.mean(oni_neg_counts)), 4),
    "ensemble_wbt_spread": round(float(np.std(vals, ddof=0)), 4),
    "enso_amplitude": round(float(np.mean(enso_amp_list)), 4),
    "tropical_heat_stress_fraction": round(float(np.mean(heat_stress_frac_list)), 4),
    "sst_global_trend": round(float(np.mean(sst_trend_list)), 4),
}

with open("/app/results.json", "w") as fh:
    json.dump(results, fh, indent=2)

print("Results written to /app/results.json")
print(json.dumps(results, indent=2))
