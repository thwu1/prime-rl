#!/usr/bin/env python3
"""Generate synthetic Landsat 8 OLI/TIRS Collection 2 data for the LST pipeline task."""

import numpy as np
import json
import os
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

# Grid parameters
ROWS, COLS = 100, 100
PIXEL_SIZE = 30
X_ORIGIN = 500000
Y_ORIGIN = 4200000
EPSG = 32610

DATA_DIR = "/data/landsat"
os.makedirs(DATA_DIR, exist_ok=True)

srs = osr.SpatialReference()
srs.ImportFromEPSG(EPSG)
srs_wkt = srs.ExportToWkt()
geotransform = (X_ORIGIN, PIXEL_SIZE, 0, Y_ORIGIN, 0, -PIXEL_SIZE)


def write_geotiff(filename, data, dtype, nodata=None):
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(filename, COLS, ROWS, 1, dtype)
    ds.SetGeoTransform(geotransform)
    ds.SetProjection(srs_wkt)
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(data)
    band.FlushCache()
    ds = None


# Zone row ranges: forest(0-19), grassland(20-39), urban(40-59), bare_soil(60-79), water(80-99)
zone_rows = {
    "forest": (0, 20),
    "grassland": (20, 40),
    "urban": (40, 60),
    "bare_soil": (60, 80),
    "water": (80, 100),
}

# Band DN values per land cover type (Int16 for SR, UInt16 for thermal)
# SR: physical_reflectance = DN * 2.75e-5 + (-0.2)
# Thermal: radiance = DN * 3.342e-4 + 0.1
band_values = {
    "forest":    {"b4": 8727,  "b5": 23636, "b10": 28000},
    "grassland": {"b4": 10909, "b5": 18182, "b10": 30000},
    "urban":     {"b4": 11636, "b5": 14545, "b10": 32000},
    "bare_soil": {"b4": 14545, "b5": 15273, "b10": 31000},
    "water":     {"b4": 8000,  "b5": 7636,  "b10": 27000},
}

b4 = np.zeros((ROWS, COLS), dtype=np.int16)
b5 = np.zeros((ROWS, COLS), dtype=np.int16)
b10 = np.zeros((ROWS, COLS), dtype=np.uint16)

for zone_name, (r_start, r_end) in zone_rows.items():
    vals = band_values[zone_name]
    b4[r_start:r_end, :] = vals["b4"]
    b5[r_start:r_end, :] = vals["b5"]
    b10[r_start:r_end, :] = vals["b10"]

# Add reproducible spatial noise
np.random.seed(42)
b4 = b4 + np.random.randint(-50, 51, (ROWS, COLS)).astype(np.int16)
b5 = b5 + np.random.randint(-50, 51, (ROWS, COLS)).astype(np.int16)
b10 = (b10.astype(np.int32) + np.random.randint(-100, 101, (ROWS, COLS))).clip(0, 65535).astype(np.uint16)

write_geotiff(os.path.join(DATA_DIR, "SR_B4.tif"), b4, gdal.GDT_Int16)
write_geotiff(os.path.join(DATA_DIR, "SR_B5.tif"), b5, gdal.GDT_Int16)
write_geotiff(os.path.join(DATA_DIR, "B10_L1.tif"), b10, gdal.GDT_UInt16)

# QA_PIXEL — Landsat Collection 2 bit-packed quality flags (UInt16)
# Bit 0: Fill, 1: Dilated Cloud, 2: Cirrus, 3: Cloud, 4: Cloud Shadow,
# 5: Snow, 6: Clear, 7: Water, 8-9: Cloud Conf, 10-11: Shadow Conf,
# 12-13: Snow Conf, 14-15: Cirrus Conf
qa_clear_land = 21824   # bits: 6,8,10,12,14 (clear + low confidence all)
qa_clear_water = 21952  # bits: 6,7,8,10,12,14 (clear + water)
qa_cloud = 22280        # bit 3 + high cloud conf (bits 8-9=3)
qa_shadow = 23824       # bit 4 + high shadow conf (bits 10-11=3)

qa = np.full((ROWS, COLS), qa_clear_land, dtype=np.uint16)
qa[80:100, :] = qa_clear_water

# Cloud regions
qa[8:14, 35:55] = qa_cloud       # 6x20=120 pixels in forest
qa[45:51, 60:80] = qa_cloud      # 6x20=120 pixels in urban

# Cloud shadow regions (shifted from clouds)
qa[14:20, 33:53] = qa_shadow     # 6x20=120 pixels in forest
qa[51:57, 58:78] = qa_shadow     # 6x20=120 pixels in urban

write_geotiff(os.path.join(DATA_DIR, "QA_PIXEL.tif"), qa, gdal.GDT_UInt16)

# DEM — Gaussian hill centered at pixel (50,50)
row_idx, col_idx = np.mgrid[0:ROWS, 0:COLS]
dem = (200.0 + 400.0 * np.exp(-((row_idx - 50)**2 + (col_idx - 50)**2) / (2.0 * 25**2))).astype(np.float32)
write_geotiff(os.path.join(DATA_DIR, "DEM.tif"), dem, gdal.GDT_Float32)

# MTL.json — Landsat 8 radiometric calibration metadata
mtl = {
    "LANDSAT_METADATA_FILE": {
        "IMAGE_ATTRIBUTES": {
            "SPACECRAFT_ID": "LANDSAT_8",
            "SENSOR_ID": "OLI_TIRS",
            "DATE_ACQUIRED": "2024-07-15",
            "SCENE_CENTER_TIME": "18:30:00.000000Z",
            "CLOUD_COVER": 12.5,
            "SUN_ELEVATION": 65.3,
            "SUN_AZIMUTH": 135.2
        },
        "LEVEL1_RADIOMETRIC_RESCALING": {
            "RADIANCE_MULT_BAND_10": 3.3420e-04,
            "RADIANCE_ADD_BAND_10": 0.10000
        },
        "LEVEL1_THERMAL_CONSTANTS": {
            "K1_CONSTANT_BAND_10": 774.8853,
            "K2_CONSTANT_BAND_10": 1321.0789
        },
        "LEVEL2_SURFACE_REFLECTANCE_PARAMETERS": {
            "REFLECTANCE_MULT_BAND_4": 2.75e-05,
            "REFLECTANCE_ADD_BAND_4": -0.2,
            "REFLECTANCE_MULT_BAND_5": 2.75e-05,
            "REFLECTANCE_ADD_BAND_5": -0.2
        },
        "PROJECTION_ATTRIBUTES": {
            "MAP_PROJECTION": "UTM",
            "UTM_ZONE": 10,
            "DATUM": "WGS84",
            "ELLIPSOID": "WGS84",
            "GRID_CELL_SIZE_REFLECTIVE": 30,
            "GRID_CELL_SIZE_THERMAL": 30
        }
    }
}
with open(os.path.join(DATA_DIR, "MTL.json"), "w") as f:
    json.dump(mtl, f, indent=2)

# parameters.json — Numerical parameters only (no formulas, no algorithm descriptions).
# Agent must supply algorithmic knowledge from domain expertise.
params = {
    "qa_pixel_bit_layout": {
        "0": "fill",
        "1": "dilated_cloud",
        "2": "cirrus",
        "3": "cloud",
        "4": "cloud_shadow",
        "5": "snow",
        "6": "clear",
        "7": "water",
        "8": "cloud_confidence_low",
        "9": "cloud_confidence_high",
        "10": "cloud_shadow_confidence_low",
        "11": "cloud_shadow_confidence_high",
        "12": "snow_confidence_low",
        "13": "snow_confidence_high",
        "14": "cirrus_confidence_low",
        "15": "cirrus_confidence_high"
    },
    "surface_reflectance": {
        "scale_multiply": 2.75e-05,
        "scale_add": -0.2
    },
    "thermal": {
        "wavelength_m": 10.895e-06,
        "rho_mK": 0.014388
    },
    "emissivity": {
        "ndvi_soil_threshold": 0.2,
        "ndvi_vegetation_threshold": 0.5,
        "emissivity_soil": 0.97,
        "emissivity_vegetation": 0.99
    },
    "nodata_value": -9999
}
with open(os.path.join(DATA_DIR, "parameters.json"), "w") as f:
    json.dump(params, f, indent=2)

# zones.geojson — Three analysis zones (UTM coordinates matching raster CRS)
zones = {
    "type": "FeatureCollection",
    "name": "analysis_zones",
    "crs_note": "Coordinates in EPSG:32610 (UTM Zone 10N), matching input rasters",
    "features": [
        {
            "type": "Feature",
            "properties": {"zone_name": "forest_grassland"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[500000, 4198800], [503000, 4198800],
                                 [503000, 4200000], [500000, 4200000],
                                 [500000, 4198800]]]
            }
        },
        {
            "type": "Feature",
            "properties": {"zone_name": "urban_bare"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[500000, 4197600], [503000, 4197600],
                                 [503000, 4198800], [500000, 4198800],
                                 [500000, 4197600]]]
            }
        },
        {
            "type": "Feature",
            "properties": {"zone_name": "lake"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[500000, 4197000], [503000, 4197000],
                                 [503000, 4197600], [500000, 4197600],
                                 [500000, 4197000]]]
            }
        }
    ]
}
with open(os.path.join(DATA_DIR, "zones.geojson"), "w") as f:
    json.dump(zones, f, indent=2)

# Verify all files were created
expected = ["SR_B4.tif", "SR_B5.tif", "B10_L1.tif", "QA_PIXEL.tif",
            "DEM.tif", "MTL.json", "parameters.json", "zones.geojson"]
for fn in expected:
    fp = os.path.join(DATA_DIR, fn)
    assert os.path.isfile(fp), f"MISSING: {fp}"
    assert os.path.getsize(fp) > 0, f"EMPTY: {fp}"

print("Synthetic Landsat data generation complete.")
print(f"  Files written to {DATA_DIR}/")
print(f"  Grid: {ROWS}x{COLS}, {PIXEL_SIZE}m resolution, EPSG:{EPSG}")
print(f"  Cloud pixels: {int(np.sum(qa == qa_cloud))}, Shadow pixels: {int(np.sum(qa == qa_shadow))}")
