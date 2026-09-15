#!/usr/bin/env python3
"""Generate synthetic Landsat 9 Collection 2 Level-2 test data."""

import numpy as np
import os
import json
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

np.random.seed(12345)

DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)

ROWS, COLS = 200, 200
PIXEL_SIZE = 30.0
UL_X = 500000.0
UL_Y = 3100000.0

crs = CRS.from_epsg(32617)
transform = from_origin(UL_X, UL_Y, PIXEL_SIZE, PIXEL_SIZE)

SCALE_FACTOR = 0.0000275
OFFSET = -0.2

LAND_COVER = {
    'vegetation': {
        'blue': 0.04, 'green': 0.08, 'red': 0.05,
        'nir': 0.45, 'swir16': 0.18, 'swir22': 0.08
    },
    'water': {
        'blue': 0.08, 'green': 0.06, 'red': 0.04,
        'nir': 0.02, 'swir16': 0.01, 'swir22': 0.005
    },
    'urban': {
        'blue': 0.10, 'green': 0.12, 'red': 0.15,
        'nir': 0.20, 'swir16': 0.28, 'swir22': 0.22
    },
    'bare_soil': {
        'blue': 0.14, 'green': 0.17, 'red': 0.22,
        'nir': 0.28, 'swir16': 0.32, 'swir22': 0.28
    }
}

BANDS = ['blue', 'green', 'red', 'nir', 'swir16', 'swir22']
BAND_NUMBERS = {'blue': 2, 'green': 3, 'red': 4, 'nir': 5, 'swir16': 6, 'swir22': 7}


def create_band_data(band_name):
    data = np.zeros((ROWS, COLS), dtype=np.uint16)
    noise_std = 0.005
    for region, (r_slice, c_slice) in [
        ('vegetation', (slice(0, 100), slice(0, 100))),
        ('water', (slice(0, 100), slice(100, 200))),
        ('urban', (slice(100, 200), slice(0, 100))),
        ('bare_soil', (slice(100, 200), slice(100, 200)))
    ]:
        base_sr = LAND_COVER[region][band_name]
        noise = np.random.normal(0, noise_std, (100, 100))
        sr_values = np.clip(base_sr + noise, 0.001, 0.999)
        dn_values = ((sr_values - OFFSET) / SCALE_FACTOR).astype(np.uint16)
        data[r_slice, c_slice] = dn_values
    return data


def create_qa_pixel():
    qa = np.zeros((ROWS, COLS), dtype=np.uint16)
    # Default: Clear (bit 6)
    qa[:, :] = (1 << 6)
    # Water pixels: set Water bit (7), clear Clear bit (6)
    qa[0:100, 100:200] = (1 << 7)
    # Fill pixels at corners (bit 0)
    qa[0:3, 0:3] = (1 << 0)
    qa[0:3, 197:200] = (1 << 0)
    # Dilated Cloud (bit 1) around cloud edges — buffer zone
    qa[28:30, 18:82] = (1 << 1)
    qa[50:52, 18:82] = (1 << 1)
    # Cloud (bit 3) + high cloud confidence (bits 8-9 = 3)
    qa[30:50, 20:80] = (1 << 3) | (3 << 8)
    # Cloud Shadow (bit 4) + high confidence (bits 10-11 = 3)
    qa[55:75, 35:95] = (1 << 4) | (3 << 10)
    # Cirrus (bit 2) + high cirrus confidence (bits 14-15 = 3)
    qa[140:160, 140:160] = (1 << 2) | (3 << 14)
    return qa


def write_geotiff(filename, data, nodata=None):
    profile = {
        'driver': 'GTiff',
        'dtype': str(data.dtype),
        'width': COLS,
        'height': ROWS,
        'count': 1,
        'crs': crs,
        'transform': transform,
    }
    if nodata is not None:
        profile['nodata'] = nodata
    with rasterio.open(filename, 'w', **profile) as dst:
        dst.write(data, 1)


# Write spectral bands
for band_name in BANDS:
    band_num = BAND_NUMBERS[band_name]
    data = create_band_data(band_name)
    write_geotiff(os.path.join(DATA_DIR, f"LC09_SR_B{band_num}.TIF"), data, nodata=0)

# Write QA_PIXEL
write_geotiff(os.path.join(DATA_DIR, "LC09_QA_PIXEL.TIF"), create_qa_pixel())

# Write metadata
metadata = {
    "LANDSAT_PRODUCT_ID": "LC09_L2SP_017041_20230615_20230618_02_T1",
    "SPACECRAFT_ID": "LANDSAT_9",
    "SENSOR_ID": "OLI_TIRS",
    "DATE_ACQUIRED": "2023-06-15",
    "COLLECTION_NUMBER": 2,
    "COLLECTION_CATEGORY": "T1",
    "PROCESSING_LEVEL": "L2SP",
    "MAP_PROJECTION": "UTM",
    "UTM_ZONE": 17,
    "DATUM": "WGS84",
    "GRID_CELL_SIZE_REFLECTIVE": 30.0,
    "SUN_ELEVATION": 68.42,
    "SUN_AZIMUTH": 122.35,
    "CLOUD_COVER": 12.5,
    "LEVEL2_SURFACE_REFLECTANCE": {
        "SR_BAND_SCALE_FACTOR": 0.0000275,
        "SR_BAND_OFFSET": -0.2,
        "SR_BANDS": {
            "SR_B2": {"name": "blue", "wavelength_nm": "452-512"},
            "SR_B3": {"name": "green", "wavelength_nm": "533-590"},
            "SR_B4": {"name": "red", "wavelength_nm": "636-673"},
            "SR_B5": {"name": "nir08", "wavelength_nm": "851-879"},
            "SR_B6": {"name": "swir16", "wavelength_nm": "1566-1651"},
            "SR_B7": {"name": "swir22", "wavelength_nm": "2107-2294"}
        }
    },
    "QA_PIXEL": {
        "description": "Pixel quality assessment band",
        "bit_index": {
            "0": "Fill",
            "1": "Dilated Cloud",
            "2": "Cirrus (high confidence)",
            "3": "Cloud",
            "4": "Cloud Shadow",
            "5": "Snow",
            "6": "Clear",
            "7": "Water"
        },
        "confidence_bits": {
            "8-9": "Cloud Confidence (0=None, 1=Low, 2=Medium, 3=High)",
            "10-11": "Cloud Shadow Confidence",
            "12-13": "Snow/Ice Confidence",
            "14-15": "Cirrus Confidence"
        }
    }
}

with open(os.path.join(DATA_DIR, "metadata.json"), 'w') as f:
    json.dump(metadata, f, indent=2)

# Write analysis zones GeoJSON
P = PIXEL_SIZE
zones_geojson = {
    "type": "FeatureCollection",
    "crs": {
        "type": "name",
        "properties": {"name": "urn:ogc:def:crs:EPSG::32617"}
    },
    "features": [
        {
            "type": "Feature",
            "properties": {"zone_id": 1, "zone_name": "northwest_forest"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [UL_X + 5*P, UL_Y - 95*P],
                    [UL_X + 95*P, UL_Y - 95*P],
                    [UL_X + 95*P, UL_Y - 5*P],
                    [UL_X + 5*P, UL_Y - 5*P],
                    [UL_X + 5*P, UL_Y - 95*P]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {"zone_id": 2, "zone_name": "northeast_water"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [UL_X + 105*P, UL_Y - 95*P],
                    [UL_X + 195*P, UL_Y - 95*P],
                    [UL_X + 195*P, UL_Y - 5*P],
                    [UL_X + 105*P, UL_Y - 5*P],
                    [UL_X + 105*P, UL_Y - 95*P]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {"zone_id": 3, "zone_name": "southwest_urban"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [UL_X + 5*P, UL_Y - 195*P],
                    [UL_X + 95*P, UL_Y - 195*P],
                    [UL_X + 95*P, UL_Y - 105*P],
                    [UL_X + 5*P, UL_Y - 105*P],
                    [UL_X + 5*P, UL_Y - 195*P]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {"zone_id": 4, "zone_name": "southeast_barren"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [UL_X + 105*P, UL_Y - 195*P],
                    [UL_X + 195*P, UL_Y - 195*P],
                    [UL_X + 195*P, UL_Y - 105*P],
                    [UL_X + 105*P, UL_Y - 105*P],
                    [UL_X + 105*P, UL_Y - 195*P]
                ]]
            }
        }
    ]
}

with open(os.path.join(DATA_DIR, "analysis_zones.geojson"), 'w') as f:
    json.dump(zones_geojson, f, indent=2)

print("Synthetic data generation complete.")
