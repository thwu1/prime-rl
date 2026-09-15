#!/usr/bin/env python3
"""Generate synthetic CMIP6-like Zarr stores for climate risk analysis task.

Creates zarr v2 stores directly using numpy + json (no zarr library needed).
"""

import numpy as np
import json
import csv
import os


# ── Zarr v2 store writing helpers (no zarr library dependency) ──


def _write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def create_zarr_group(path, attrs=None):
    """Create a zarr v2 group directory with .zgroup and optional .zattrs."""
    os.makedirs(path, exist_ok=True)
    _write_json(os.path.join(path, ".zgroup"), {"zarr_format": 2})
    if attrs:
        _write_json(os.path.join(path, ".zattrs"), attrs)


def create_zarr_array(group_path, name, data, chunks=None, attrs=None):
    """Write a zarr v2 array (uncompressed) into the given group directory."""
    arr_path = os.path.join(group_path, name)
    os.makedirs(arr_path, exist_ok=True)

    data = np.ascontiguousarray(data)
    if chunks is None:
        chunks = data.shape

    fill_val = 0.0 if np.issubdtype(data.dtype, np.floating) else 0

    meta = {
        "chunks": list(chunks),
        "compressor": None,
        "dtype": data.dtype.str,
        "fill_value": fill_val,
        "filters": None,
        "order": "C",
        "shape": list(data.shape),
        "zarr_format": 2,
    }
    _write_json(os.path.join(arr_path, ".zarray"), meta)

    if attrs:
        _write_json(os.path.join(arr_path, ".zattrs"), attrs)

    # Write raw chunk files
    chunk_counts = tuple(
        int(np.ceil(s / c)) for s, c in zip(data.shape, chunks)
    )
    for idx in np.ndindex(*chunk_counts):
        slices = tuple(
            slice(i * c, min((i + 1) * c, s))
            for i, c, s in zip(idx, chunks, data.shape)
        )
        chunk_data = np.ascontiguousarray(data[slices])
        chunk_key = ".".join(str(i) for i in idx)
        chunk_data.tofile(os.path.join(arr_path, chunk_key))


# ── Grid configuration ──

nlat, nlon = 36, 72
lats = np.linspace(-87.5, 87.5, nlat)
lons = np.linspace(2.5, 357.5, nlon)

ntime = 60       # 5 years monthly for tas/hurs
ntime_sst = 240  # 20 years monthly for SST

models = ["CESM2-TEST", "GFDL-TEST", "MIROC-TEST"]
experiments = ["historical", "ssp245", "ssp585"]

model_temp_bias = {"CESM2-TEST": 0.0, "GFDL-TEST": -0.5, "MIROC-TEST": 0.8}
scenario_warming = {"historical": 0.0, "ssp245": 1.5, "ssp585": 3.0}
model_seed_base = {"CESM2-TEST": 1000, "GFDL-TEST": 2000, "MIROC-TEST": 3000}
exp_seed_offset = {"historical": 100, "ssp245": 200, "ssp585": 300}

base_dir = "/app/data"
zarr_dir = os.path.join(base_dir, "zarr")
catalog_dir = os.path.join(base_dir, "catalog")
os.makedirs(zarr_dir, exist_ok=True)
os.makedirs(catalog_dir, exist_ok=True)

catalog_rows = []

for model in models:
    for experiment in experiments:
        seed_tas = model_seed_base[model] + exp_seed_offset[experiment] + 10
        seed_hurs = model_seed_base[model] + exp_seed_offset[experiment] + 20

        # Temperature (K): latitudinal gradient + seasonal cycle + offset + noise
        rng_t = np.random.RandomState(seed_tas)
        lat_profile = 280.0 + 20.0 * np.cos(np.deg2rad(lats))
        lat_field = np.broadcast_to(
            lat_profile[np.newaxis, :, np.newaxis], (ntime, nlat, nlon)
        ).copy()

        months = np.arange(ntime)
        seasonal = 5.0 * np.sin(2.0 * np.pi * months / 12.0)
        lat_amplitude = np.abs(np.sin(np.deg2rad(lats)))
        for t in range(ntime):
            lat_field[t] += seasonal[t] * lat_amplitude[:, np.newaxis]

        offset = model_temp_bias[model] + scenario_warming[experiment]
        noise = rng_t.normal(0, 2.0, (ntime, nlat, nlon))
        tas = (lat_field + offset + noise).astype(np.float32)

        # Humidity (%): wet tropics + noise, clipped to [5, 100]
        rng_h = np.random.RandomState(seed_hurs)
        hurs_profile = 40.0 + 30.0 * np.cos(np.deg2rad(lats))
        hurs_base = np.broadcast_to(
            hurs_profile[np.newaxis, :, np.newaxis], (ntime, nlat, nlon)
        ).copy()
        noise_h = rng_h.normal(0, 5.0, (ntime, nlat, nlon))
        hurs = np.clip(hurs_base + noise_h, 5.0, 100.0).astype(np.float32)

        # MIROC-TEST stores humidity as dimensionless fraction [0, 1]
        if model == "MIROC-TEST":
            hurs = (hurs / 100.0).astype(np.float32)
            hurs_units = "1"
        else:
            hurs_units = "%"

        # Save Zarr store (both variables in one store)
        store_name = f"{model}_{experiment}"
        store_path = os.path.join(zarr_dir, store_name)

        group_attrs = {
            "source_id": model,
            "experiment_id": experiment,
            "member_id": "r1i1p1f1",
            "table_id": "Amon",
            "grid_label": "gn",
            "activity_id": "CMIP" if experiment == "historical" else "ScenarioMIP",
            "institution_id": "TEST-INST",
        }
        create_zarr_group(store_path, attrs=group_attrs)

        create_zarr_array(
            store_path, "tas", tas,
            chunks=(12, nlat, nlon),
            attrs={"units": "K", "long_name": "Near-Surface Air Temperature"},
        )
        create_zarr_array(
            store_path, "hurs", hurs,
            chunks=(12, nlat, nlon),
            attrs={"units": hurs_units, "long_name": "Near-Surface Relative Humidity"},
        )
        create_zarr_array(
            store_path, "lat", lats.astype(np.float64),
            attrs={"units": "degrees_north"},
        )
        create_zarr_array(
            store_path, "lon", lons.astype(np.float64),
            attrs={"units": "degrees_east"},
        )
        create_zarr_array(
            store_path, "time", np.arange(ntime, dtype=np.int32),
            attrs={"units": "months since 2000-01-01", "calendar": "standard"},
        )

        for var in ["tas", "hurs"]:
            catalog_rows.append(
                {
                    "activity_id": group_attrs["activity_id"],
                    "institution_id": "TEST-INST",
                    "source_id": model,
                    "experiment_id": experiment,
                    "member_id": "r1i1p1f1",
                    "table_id": "Amon",
                    "variable_id": var,
                    "grid_label": "gn",
                    "zstore": store_path,
                    "version": "v20230101",
                }
            )

# --- SST data for ONI ---
sst_path = os.path.join(zarr_dir, "CESM2-TEST_historical_tos")
rng_sst = np.random.RandomState(12345)

sst_base = 15.0 + 15.0 * np.cos(np.deg2rad(lats))
sst_base_3d = np.broadcast_to(
    sst_base[np.newaxis, :, np.newaxis], (ntime_sst, nlat, nlon)
).copy()

months_sst = np.arange(ntime_sst)
sst_seasonal = 2.0 * np.sin(2.0 * np.pi * months_sst / 12.0)
for t in range(ntime_sst):
    sst_base_3d[t] += sst_seasonal[t]

# ENSO signal: oscillation injected into Nino 3.4 region
enso = np.zeros(ntime_sst)
for i in range(ntime_sst):
    enso[i] = 1.5 * np.sin(2.0 * np.pi * i / 42.0) + 0.8 * np.sin(
        2.0 * np.pi * i / 30.0
    )

nino_lat_mask = np.abs(lats) <= 5.0
nino_lon_mask = (lons >= 190.0) & (lons <= 240.0)
for t in range(ntime_sst):
    for j in range(nlat):
        for k in range(nlon):
            if nino_lat_mask[j] and nino_lon_mask[k]:
                sst_base_3d[t, j, k] += enso[t]

noise_sst = rng_sst.normal(0, 0.5, (ntime_sst, nlat, nlon))
tos = (sst_base_3d + noise_sst).astype(np.float32)

sst_group_attrs = {
    "source_id": "CESM2-TEST",
    "experiment_id": "historical",
    "member_id": "r1i1p1f1",
    "table_id": "Omon",
    "variable_id": "tos",
    "grid_label": "gn",
    "activity_id": "CMIP",
    "institution_id": "TEST-INST",
}
create_zarr_group(sst_path, attrs=sst_group_attrs)

create_zarr_array(
    sst_path, "tos", tos,
    chunks=(12, nlat, nlon),
    attrs={"units": "degC", "long_name": "Sea Surface Temperature"},
)
create_zarr_array(
    sst_path, "lat", lats.astype(np.float64),
    attrs={"units": "degrees_north"},
)
create_zarr_array(
    sst_path, "lon", lons.astype(np.float64),
    attrs={"units": "degrees_east"},
)
create_zarr_array(
    sst_path, "time", np.arange(ntime_sst, dtype=np.int32),
    attrs={"units": "months since 2000-01-01", "calendar": "standard"},
)

catalog_rows.append(
    {
        "activity_id": "CMIP",
        "institution_id": "TEST-INST",
        "source_id": "CESM2-TEST",
        "experiment_id": "historical",
        "member_id": "r1i1p1f1",
        "table_id": "Omon",
        "variable_id": "tos",
        "grid_label": "gn",
        "zstore": sst_path,
        "version": "v20230101",
    }
)

# --- Write catalog ---
fieldnames = [
    "activity_id", "institution_id", "source_id", "experiment_id",
    "member_id", "table_id", "variable_id", "grid_label", "zstore", "version",
]
csv_path = os.path.join(catalog_dir, "catalog.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in catalog_rows:
        writer.writerow(row)

json_desc = {
    "esmcat_version": "0.1.0",
    "id": "synthetic-cmip6",
    "description": "Synthetic CMIP6-like test catalog",
    "catalog_file": csv_path,
    "attributes": [
        {"column_name": c}
        for c in fieldnames
        if c not in ("zstore", "version")
    ],
    "assets": {"column_name": "zstore", "format": "zarr"},
    "aggregation_control": {
        "variable_column_name": "variable_id",
        "groupby_attrs": [
            "source_id", "experiment_id", "member_id", "table_id", "grid_label",
        ],
        "aggregations": [
            {"type": "union", "attribute_name": "variable_id"}
        ],
    },
}

json_path = os.path.join(catalog_dir, "catalog.json")
with open(json_path, "w") as f:
    json.dump(json_desc, f, indent=2)

print(f"Generated {len(catalog_rows)} catalog entries")
print(f"Zarr stores: {zarr_dir}")
print(f"Catalog: {catalog_dir}")
