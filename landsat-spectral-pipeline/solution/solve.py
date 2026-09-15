#!/usr/bin/env python3
"""Solution: Corrected Landsat surface reflectance analysis pipeline with quality assessment."""

import os
import json
import csv
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject, Resampling

DATA_DIR = "/data"
OUTPUT_DIR = "/app/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Read metadata ---
with open(os.path.join(DATA_DIR, "metadata.json")) as f:
    metadata = json.load(f)

sr_config = metadata["LEVEL2_SURFACE_REFLECTANCE"]
scale_factor = sr_config["SR_BAND_SCALE_FACTOR"]
offset = sr_config["SR_BAND_OFFSET"]

# --- Read QA_PIXEL and get spatial reference info ---
with rasterio.open(os.path.join(DATA_DIR, "LC09_QA_PIXEL.TIF")) as qa_ds:
    qa_data = qa_ds.read(1)
    src_profile = qa_ds.profile.copy()
    src_transform = qa_ds.transform
    src_crs = qa_ds.crs
    rows, cols = qa_data.shape

# --- Step 1: Cloud mask ---
# FIX: Check all contamination bits 0-4 (Fill, Dilated Cloud, Cirrus, Cloud, Cloud Shadow)
# Original pipeline only checked bits 3-4 (Cloud, Cloud Shadow), missing Fill, Dilated Cloud, Cirrus
mask_bits = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)
cloud_mask = np.where((qa_data & mask_bits) == 0, 1, 0).astype(np.uint8)
clear = cloud_mask == 1

# Also compute original (broken) mask for defect impact analysis
broken_mask_bits = (1 << 3) | (1 << 4)
broken_clear = (qa_data & broken_mask_bits) == 0


def write_tif(filename, data, nodata=None):
    profile = {
        'driver': 'GTiff',
        'dtype': str(data.dtype),
        'width': cols,
        'height': rows,
        'count': 1,
        'crs': src_crs,
        'transform': src_transform,
    }
    if nodata is not None:
        profile['nodata'] = float(nodata)
    with rasterio.open(filename, 'w', **profile) as dst:
        dst.write(data, 1)


write_tif(os.path.join(OUTPUT_DIR, "cloud_mask.tif"), cloud_mask)

# --- Step 2: Read bands and calibrate to surface reflectance ---
# FIX: Use addition (dn * scale_factor + offset), not subtraction
# Original pipeline had: dn * scale_factor - offset
# offset is -0.2, so subtraction gives dn*scale + 0.2 (inflating by 0.4 total error)
def read_band_sr(band_num):
    with rasterio.open(os.path.join(DATA_DIR, f"LC09_SR_B{band_num}.TIF")) as ds:
        dn = ds.read(1).astype(np.float64)
    return dn * scale_factor + offset


green_sr = read_band_sr(3)
red_sr = read_band_sr(4)
nir_sr = read_band_sr(5)
swir1_sr = read_band_sr(6)

# --- Step 3: Compute spectral indices ---
NODATA = -9999.0

# NDVI
ndvi = np.full((rows, cols), NODATA, dtype=np.float32)
denom_ndvi = nir_sr + red_sr
valid_ndvi = clear & (denom_ndvi != 0)
ndvi[valid_ndvi] = ((nir_sr[valid_ndvi] - red_sr[valid_ndvi])
                    / denom_ndvi[valid_ndvi]).astype(np.float32)

write_tif(os.path.join(OUTPUT_DIR, "ndvi.tif"), ndvi, nodata=NODATA)

# MNDWI
mndwi = np.full((rows, cols), NODATA, dtype=np.float32)
denom_mndwi = green_sr + swir1_sr
valid_mndwi = clear & (denom_mndwi != 0)
mndwi[valid_mndwi] = ((green_sr[valid_mndwi] - swir1_sr[valid_mndwi])
                       / denom_mndwi[valid_mndwi]).astype(np.float32)

write_tif(os.path.join(OUTPUT_DIR, "mndwi.tif"), mndwi, nodata=NODATA)

# NDBI (for classification only)
ndbi = np.full((rows, cols), NODATA, dtype=np.float32)
denom_ndbi = swir1_sr + nir_sr
valid_ndbi = clear & (denom_ndbi != 0)
ndbi[valid_ndbi] = ((swir1_sr[valid_ndbi] - nir_sr[valid_ndbi])
                    / denom_ndbi[valid_ndbi]).astype(np.float32)

# --- Step 4: Land cover classification ---
land_cover = np.zeros((rows, cols), dtype=np.uint8)

# Class 1: Water (MNDWI > 0.0)
water = clear & (mndwi > 0.0)
land_cover[water] = 1

# Class 2: Vegetation (NDVI > 0.3 AND MNDWI <= 0.0)
vegetation = clear & (ndvi > 0.3) & (mndwi <= 0.0)
land_cover[vegetation] = 2

# Class 3: Built-up (NDBI > NDVI AND NDVI <= 0.3 AND MNDWI <= 0.0)
built_up = clear & (ndbi > ndvi) & (ndvi <= 0.3) & (mndwi <= 0.0)
land_cover[built_up] = 3

# Class 4: Bare soil (remaining clear pixels)
bare = clear & (land_cover == 0)
land_cover[bare] = 4

write_tif(os.path.join(OUTPUT_DIR, "land_cover.tif"), land_cover, nodata=0)

# --- Step 5: Zonal statistics ---
# FIX: Count only clear pixels, not total zone pixels
with open(os.path.join(DATA_DIR, "analysis_zones.geojson")) as f:
    geojson = json.load(f)

zone_info = {}
shapes = []
for feature in geojson["features"]:
    zid = feature["properties"]["zone_id"]
    zname = feature["properties"]["zone_name"]
    zone_info[zid] = zname
    shapes.append((feature["geometry"], zid))

zone_raster = rasterize(
    shapes,
    out_shape=(rows, cols),
    transform=src_transform,
    fill=0,
    dtype=np.int32,
)

with open(os.path.join(OUTPUT_DIR, "zonal_stats.csv"), "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["zone_id", "zone_name", "mean_ndvi", "mean_mndwi", "clear_pixel_count"])
    for zid in sorted(zone_info.keys()):
        zone_clear = (zone_raster == zid) & clear
        count = int(np.sum(zone_clear))
        if count > 0:
            m_ndvi = round(float(np.mean(ndvi[zone_clear])), 4)
            m_mndwi = round(float(np.mean(mndwi[zone_clear])), 4)
        else:
            m_ndvi = 0.0
            m_mndwi = 0.0
        writer.writerow([zid, zone_info[zid], m_ndvi, m_mndwi, count])

# --- Step 6: Reproject NDVI to WGS84 ---
# FIX: Add missing reprojection deliverable
ndvi_src = os.path.join(OUTPUT_DIR, "ndvi.tif")
ndvi_dst = os.path.join(OUTPUT_DIR, "ndvi_wgs84.tif")
dst_crs = CRS.from_epsg(4326)

with rasterio.open(ndvi_src) as src:
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src.crs, dst_crs, src.width, src.height, *src.bounds
    )
    profile = src.profile.copy()
    profile.update({
        'crs': dst_crs,
        'transform': dst_transform,
        'width': dst_width,
        'height': dst_height,
    })

    with rasterio.open(ndvi_dst, 'w', **profile) as dst:
        reproject(
            source=rasterio.band(src, 1),
            destination=rasterio.band(dst, 1),
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
            src_nodata=NODATA,
            dst_nodata=NODATA,
        )

# --- Step 7: Quality Assessment ---
total_pixels = rows * cols

# Defect 1: QA masking gaps — count pixels that were false-clear under broken mask
# These are pixels with Fill/Dilated Cloud/Cirrus bits set that the old mask missed
missed_bits = (1 << 0) | (1 << 1) | (1 << 2)
false_clear_count = int(np.sum(broken_clear & ((qa_data & missed_bits) != 0)))

# Defect 2: Calibration sign error — all clear pixels were systematically wrong
calibration_affected = int(np.sum(clear))

# Defect 3: Zonal stats error — count contaminated pixels across all zones
zonal_contaminated = 0
for zid in sorted(zone_info.keys()):
    in_zone = zone_raster == zid
    zone_total = int(np.sum(in_zone))
    zone_clear_count = int(np.sum(in_zone & clear))
    zonal_contaminated += (zone_total - zone_clear_count)

# Defect 4: Missing reprojection — entire scene affected
reproject_affected = total_pixels

# Calibration validation: NIR at the NW vegetation validation site
# The validation report references the "dense canopy validation site in the northwest quadrant"
# Use a representative area in the vegetation region that is clear
veg_validation = np.zeros((rows, cols), dtype=bool)
veg_validation[8:20, 8:20] = True
veg_validation &= clear
nir_field_ref = 0.45  # from validation report
nir_corrected_mean = float(np.mean(nir_sr[veg_validation]))
nir_residual = abs(nir_corrected_mean - nir_field_ref)

# Scene quality metrics
clear_total = int(np.sum(clear))
clear_fraction = clear_total / total_pixels

# Per-zone quality
zone_quality_list = []
for zid in sorted(zone_info.keys()):
    in_zone = zone_raster == zid
    zt = int(np.sum(in_zone))
    zc = int(np.sum(in_zone & clear))
    frac = zc / zt if zt > 0 else 0.0
    if frac > 0.9:
        usability = "high"
    elif frac > 0.6:
        usability = "medium"
    else:
        usability = "low"
    zone_quality_list.append({
        "zone_id": zid,
        "clear_fraction": round(frac, 4),
        "data_usability": usability
    })

# Usability grade
if clear_fraction > 0.95:
    grade = "A"
elif clear_fraction > 0.85:
    grade = "B"
elif clear_fraction > 0.70:
    grade = "C"
elif clear_fraction > 0.50:
    grade = "D"
else:
    grade = "F"

z1_info = next(z for z in zone_quality_list if z["zone_id"] == 1)

quality_assessment = {
    "defects": [
        {
            "id": "D1",
            "category": "qa_masking",
            "description": (
                "Cloud mask only checked Cloud (bit 3) and Cloud Shadow (bit 4) flags, "
                "missing Fill (bit 0), Dilated Cloud (bit 1), and Cirrus (bit 2). "
                "Fill pixels at scene borders, dilated cloud buffer zones around cloud bodies, "
                "and cirrus-contaminated regions were incorrectly passed as clear observations, "
                "propagating invalid data into all downstream spectral indices and classification."
            ),
            "affected_pixel_count": false_clear_count,
            "severity": "critical"
        },
        {
            "id": "D2",
            "category": "calibration",
            "description": (
                "DN-to-surface-reflectance conversion used subtraction "
                "(dn * scale_factor - offset) instead of addition (dn * scale_factor + offset). "
                "Since offset is -0.2, subtraction yields dn*scale + 0.2 instead of dn*scale - 0.2, "
                "inflating all reflectance values by 0.4. This systematic overestimation compressed "
                "NDVI dynamic range (e.g. dense vegetation NDVI read ~0.31 instead of ~0.80) and "
                "collapsed MNDWI discrimination between water and non-water surfaces."
            ),
            "affected_pixel_count": calibration_affected,
            "severity": "critical"
        },
        {
            "id": "D3",
            "category": "zonal_statistics",
            "description": (
                "Zonal statistics reported total zone pixel count as clear_pixel_count instead "
                "of counting only uncontaminated (cloud-mask-clear) pixels within each zone. "
                "This inflated counts for zones overlapping cloud, cloud shadow, dilated cloud, "
                "and cirrus features, misrepresenting data availability and quality per zone."
            ),
            "affected_pixel_count": zonal_contaminated,
            "severity": "major"
        },
        {
            "id": "D4",
            "category": "product_completeness",
            "description": (
                "WGS84 (EPSG:4326) geographic-coordinate reprojection of the NDVI product was "
                "not generated. This deliverable is required for web mapping service integration "
                "and was missing entirely from pipeline output."
            ),
            "affected_pixel_count": reproject_affected,
            "severity": "major"
        }
    ],
    "scene_quality": {
        "clear_pixel_fraction": round(clear_fraction, 4),
        "usability_grade": grade,
        "grade_justification": (
            f"Scene has {round(clear_fraction * 100, 1)}% clear pixels after corrected quality masking. "
            f"Cloud and cloud shadow features affect the northwest quadrant "
            f"({round((1 - z1_info['clear_fraction']) * 100, 1)}% of zone 1 contaminated), "
            f"and thin cirrus affects part of the southeast quadrant. "
            f"All four identified pipeline defects have been corrected. "
            f"Grade {grade} reflects good overall data availability with localized contamination "
            f"that reduces usability in the northwest analysis zone."
        )
    },
    "calibration_validation": {
        "nir_field_reference": nir_field_ref,
        "nir_pipeline_corrected": round(nir_corrected_mean, 4),
        "nir_residual_abs": round(nir_residual, 4),
        "calibration_status": "pass" if nir_residual < 0.05 else "fail"
    },
    "zone_quality": zone_quality_list
}

with open(os.path.join(OUTPUT_DIR, "quality_assessment.json"), "w") as f:
    json.dump(quality_assessment, f, indent=2)

print("Pipeline complete. Outputs written to /app/output/")
