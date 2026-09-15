#!/usr/bin/env python3
"""Landsat 9 Collection 2 Level-2 surface reflectance processing pipeline.
Generates derived products from calibrated surface reflectance data.
"""

import os
import json
import csv
import numpy as np
import rasterio
from rasterio.features import rasterize

DATA_DIR = "/data"
OUTPUT_DIR = "/app/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Configuration from metadata ---
with open(os.path.join(DATA_DIR, "metadata.json")) as f:
    metadata = json.load(f)

level2 = metadata["LEVEL2_SURFACE_REFLECTANCE"]
scale_factor = level2["SR_BAND_SCALE_FACTOR"]
offset = level2["SR_BAND_OFFSET"]

# --- Load QA pixel band ---
with rasterio.open(os.path.join(DATA_DIR, "LC09_QA_PIXEL.TIF")) as ds:
    qa_pixel = ds.read(1)
    ref_crs = ds.crs
    ref_transform = ds.transform
    nrows, ncols = qa_pixel.shape


# --- Cloud masking ---
# Mask out Cloud (bit 3) and Cloud Shadow (bit 4)
qa_flags = (1 << 3) | (1 << 4)
cloud_mask = np.where((qa_pixel & qa_flags) == 0, 1, 0).astype(np.uint8)
is_clear = cloud_mask == 1


def write_raster(filepath, data, nodata=None):
    profile = {
        "driver": "GTiff",
        "dtype": str(data.dtype),
        "width": ncols,
        "height": nrows,
        "count": 1,
        "crs": ref_crs,
        "transform": ref_transform,
    }
    if nodata is not None:
        profile["nodata"] = float(nodata)
    with rasterio.open(filepath, "w", **profile) as out:
        out.write(data, 1)


write_raster(os.path.join(OUTPUT_DIR, "cloud_mask.tif"), cloud_mask)


# --- Radiometric calibration ---
def load_calibrated_band(band_number):
    """Convert digital numbers to surface reflectance using Collection 2 scaling."""
    path = os.path.join(DATA_DIR, f"LC09_SR_B{band_number}.TIF")
    with rasterio.open(path) as ds:
        dn = ds.read(1).astype(np.float64)
    # Apply scaling: SR = DN * scale_factor + offset
    return dn * scale_factor - offset


green_sr = load_calibrated_band(3)
red_sr = load_calibrated_band(4)
nir_sr = load_calibrated_band(5)
swir1_sr = load_calibrated_band(6)

NODATA_VALUE = -9999.0


# --- Spectral indices ---
def normalized_difference(band_a, band_b):
    """Compute (A - B) / (A + B) with cloud masking."""
    result = np.full((nrows, ncols), NODATA_VALUE, dtype=np.float32)
    denominator = band_a + band_b
    valid = is_clear & (denominator != 0)
    result[valid] = ((band_a[valid] - band_b[valid]) /
                     denominator[valid]).astype(np.float32)
    return result


ndvi = normalized_difference(nir_sr, red_sr)
mndwi = normalized_difference(green_sr, swir1_sr)
ndbi = normalized_difference(swir1_sr, nir_sr)

write_raster(os.path.join(OUTPUT_DIR, "ndvi.tif"), ndvi, NODATA_VALUE)
write_raster(os.path.join(OUTPUT_DIR, "mndwi.tif"), mndwi, NODATA_VALUE)


# --- Land cover classification ---
land_cover = np.zeros((nrows, ncols), dtype=np.uint8)

# Priority-ordered decision tree
land_cover[is_clear & (mndwi > 0.0)] = 1                                           # Water
land_cover[is_clear & (ndvi > 0.3) & (mndwi <= 0.0)] = 2                          # Vegetation
land_cover[is_clear & (ndbi > ndvi) & (ndvi <= 0.3) & (mndwi <= 0.0)] = 3        # Built-up
land_cover[is_clear & (land_cover == 0)] = 4                                        # Bare soil

write_raster(os.path.join(OUTPUT_DIR, "land_cover.tif"), land_cover, 0)


# --- Zonal statistics ---
with open(os.path.join(DATA_DIR, "analysis_zones.geojson")) as f:
    zones_gj = json.load(f)

zone_meta = {}
zone_shapes = []
for feature in zones_gj["features"]:
    zid = feature["properties"]["zone_id"]
    zone_meta[zid] = feature["properties"]["zone_name"]
    zone_shapes.append((feature["geometry"], zid))

zone_raster = rasterize(
    zone_shapes,
    out_shape=(nrows, ncols),
    transform=ref_transform,
    fill=0,
    dtype=np.int32,
)

with open(os.path.join(OUTPUT_DIR, "zonal_stats.csv"), "w", newline="") as csvf:
    writer = csv.writer(csvf)
    writer.writerow(["zone_id", "zone_name", "mean_ndvi", "mean_mndwi",
                     "clear_pixel_count"])
    for zid in sorted(zone_meta.keys()):
        in_zone = zone_raster == zid
        pixel_count = int(np.sum(in_zone))

        zone_ndvi = ndvi[in_zone]
        zone_mndwi = mndwi[in_zone]

        valid_ndvi = zone_ndvi[zone_ndvi != NODATA_VALUE]
        valid_mndwi = zone_mndwi[zone_mndwi != NODATA_VALUE]

        mean_ndvi = round(float(np.mean(valid_ndvi)), 4) if len(valid_ndvi) > 0 else 0.0
        mean_mndwi = round(float(np.mean(valid_mndwi)), 4) if len(valid_mndwi) > 0 else 0.0

        writer.writerow([zid, zone_meta[zid], mean_ndvi, mean_mndwi, pixel_count])

print("Processing complete. Outputs in", OUTPUT_DIR)
