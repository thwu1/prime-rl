#!/usr/bin/env python3
"""Solution for CMIP6 ensemble climate risk analysis pipeline."""

import csv
import json
import os

import numpy as np
import zarr

ZARR_DIR = "/app/data/zarr"
CATALOG_CSV = "/app/data/catalog/catalog.csv"
OUTPUT_PATH = "/app/results.json"

MODELS = ["CESM2-TEST", "GFDL-TEST", "MIROC-TEST"]
EXPERIMENTS = ["historical", "ssp245", "ssp585"]


def stull_wbt(T_c, RH):
    """Stull (2011) wet-bulb temperature approximation.
    T_c in degrees Celsius, RH in percent (0-100).
    """
    return (
        T_c * np.arctan(0.151977 * np.sqrt(RH + 8.313659))
        + np.arctan(T_c + RH)
        - np.arctan(RH - 1.676331)
        + 0.00391838 * RH**1.5 * np.arctan(0.023101 * RH)
        - 4.686035
    )


def weighted_percentile(data_2d, lat, percentile):
    """Compute area-weighted percentile from a (lat, lon) field."""
    cos_lat = np.cos(np.deg2rad(lat))
    weights = np.broadcast_to(cos_lat[:, np.newaxis], data_2d.shape)
    flat_d = data_2d.ravel()
    flat_w = weights.ravel()
    mask = ~np.isnan(flat_d)
    flat_d = flat_d[mask]
    flat_w = flat_w[mask]
    idx = np.argsort(flat_d)
    sd = flat_d[idx]
    sw = flat_w[idx]
    cum = np.cumsum(sw)
    cum_norm = (cum - 0.5 * sw) / cum[-1]
    return float(np.interp(percentile / 100.0, cum_norm, sd))


def load_catalog():
    rows = []
    with open(CATALOG_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def find_store(catalog, **kwargs):
    for row in catalog:
        if all(row.get(k) == v for k, v in kwargs.items()):
            return row["zstore"]
    raise ValueError(f"No store found for {kwargs}")


def compute_wbt_extremes(catalog):
    """Compute area-weighted 90th-percentile WBT for each model/experiment."""
    wbt_extremes = {}
    for model in MODELS:
        wbt_extremes[model] = {}
        for exp in EXPERIMENTS:
            store_path = find_store(
                catalog, source_id=model, experiment_id=exp, variable_id="tas"
            )
            store = zarr.open(store_path, "r")

            tas_raw = np.array(store["tas"])
            hurs = np.array(store["hurs"])
            lat = np.array(store["lat"])

            # Convert temperature from Kelvin to Celsius
            tas_C = tas_raw - 273.15

            # Check humidity units and convert fraction to percent if needed
            hurs_units = dict(store["hurs"].attrs).get("units", "%")
            if hurs_units in ("1", "fraction"):
                hurs = hurs * 100.0

            wbt = stull_wbt(tas_C, hurs)

            ntime = wbt.shape[0]
            p90_ts = np.zeros(ntime)
            for t in range(ntime):
                p90_ts[t] = weighted_percentile(wbt[t], lat, 90)

            wbt_extremes[model][exp] = float(np.mean(p90_ts[-12:]))

    return wbt_extremes


def compute_global_mean_temp(catalog, model, experiment):
    """Compute area-weighted global mean temperature (°C) over last 12 timesteps."""
    store_path = find_store(
        catalog, source_id=model, experiment_id=experiment, variable_id="tas"
    )
    store = zarr.open(store_path, "r")

    tas_raw = np.array(store["tas"])
    lat = np.array(store["lat"])

    tas_C = tas_raw - 273.15

    cos_lat = np.cos(np.deg2rad(lat))
    weights = np.broadcast_to(cos_lat[:, np.newaxis], tas_C.shape[1:])

    global_means = []
    for t in range(tas_C.shape[0] - 12, tas_C.shape[0]):
        global_means.append(float(np.average(tas_C[t], weights=weights)))

    return float(np.mean(global_means))


def compute_oni(catalog):
    """Compute the Oceanic Nino Index from SST data."""
    store_path = find_store(catalog, variable_id="tos")
    store = zarr.open(store_path, "r")

    tos = np.array(store["tos"])
    lat = np.array(store["lat"])
    lon = np.array(store["lon"])

    # Nino 3.4 region: 5S-5N, 170W-120W (= 190E-240E)
    lat_mask = np.abs(lat) <= 5.0
    lon_mask = (lon >= 190.0) & (lon <= 240.0)

    nino_sst = tos[:, lat_mask][:, :, lon_mask]

    cos_lat = np.cos(np.deg2rad(lat[lat_mask]))
    weights = np.broadcast_to(cos_lat[:, np.newaxis], nino_sst.shape[1:])

    nino34_ts = np.array(
        [np.average(nino_sst[t], weights=weights) for t in range(nino_sst.shape[0])]
    )

    clim = np.array([np.mean(nino34_ts[m::12]) for m in range(12)])
    anom = np.array([nino34_ts[i] - clim[i % 12] for i in range(len(nino34_ts))])

    nmonths = len(anom)
    oni = np.full(nmonths, np.nan)
    for i in range(1, nmonths - 1):
        oni[i] = np.mean(anom[i - 1 : i + 2])

    return oni


def classify_enso(oni):
    """Classify El Nino and La Nina events from ONI timeseries."""
    el_nino_count = 0
    la_nina_count = 0

    consec = 0
    in_evt = False
    for v in oni:
        if not np.isnan(v) and v > 0.5:
            consec += 1
            if consec >= 5 and not in_evt:
                el_nino_count += 1
                in_evt = True
        else:
            consec = 0
            in_evt = False

    consec = 0
    in_evt = False
    for v in oni:
        if not np.isnan(v) and v < -0.5:
            consec += 1
            if consec >= 5 and not in_evt:
                la_nina_count += 1
                in_evt = True
        else:
            consec = 0
            in_evt = False

    return el_nino_count, la_nina_count


def main():
    catalog = load_catalog()

    # WBT reference
    wbt_ref = float(stull_wbt(20.0, 50.0))

    # WBT extremes
    wbt_extremes = compute_wbt_extremes(catalog)

    # Ensemble mean
    ensemble_mean = {}
    for exp in EXPERIMENTS:
        vals = [wbt_extremes[m][exp] for m in MODELS]
        ensemble_mean[exp] = float(np.mean(vals))

    # Warming amplification
    warming_amplification = {}
    for model in MODELS:
        t_hist = compute_global_mean_temp(catalog, model, "historical")
        t_ssp585 = compute_global_mean_temp(catalog, model, "ssp585")
        delta_t = t_ssp585 - t_hist
        delta_wbt = wbt_extremes[model]["ssp585"] - wbt_extremes[model]["historical"]
        warming_amplification[model] = float(delta_wbt / delta_t)

    # ONI
    oni = compute_oni(catalog)
    oni_values = [float(v) if not np.isnan(v) else None for v in oni]

    # ENSO events
    el_nino_count, la_nina_count = classify_enso(oni)

    results = {
        "wbt_reference_check": wbt_ref,
        "wbt_extremes": wbt_extremes,
        "ensemble_mean_wbt_extremes": ensemble_mean,
        "warming_amplification": warming_amplification,
        "oni": {"oni_values": oni_values},
        "enso_events": {
            "el_nino_count": el_nino_count,
            "la_nina_count": la_nina_count,
        },
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
