#!/usr/bin/env python3
"""Generate synthetic Landsat 8 scene data and flawed analysis outputs."""

import numpy as np
from osgeo import gdal, osr
import json
import os

gdal.UseExceptions()
np.random.seed(42)

NROWS, NCOLS = 200, 200
PIXEL_SIZE = 30.0
ORIGIN_X, ORIGIN_Y = 400000.0, 4500000.0
EPSG = 32618

K1 = 774.8853
K2 = 1321.0789
M_L = 3.3420e-04
A_L = 0.10000


def create_geotiff(filename, data, gdal_dtype, nodata=None):
    driver = gdal.GetDriverByName('GTiff')
    ds = driver.Create(filename, NCOLS, NROWS, 1, gdal_dtype)
    ds.SetGeoTransform([ORIGIN_X, PIXEL_SIZE, 0, ORIGIN_Y, 0, -PIXEL_SIZE])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(EPSG)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(float(nodata))
    band.WriteArray(data)
    band.FlushCache()
    ds = None


def bt_to_dn(bt_celsius):
    bt_k = bt_celsius + 273.15
    radiance = K1 / (np.exp(K2 / bt_k) - 1)
    dn = (radiance - A_L) / M_L
    return np.clip(np.round(dn), 1, 65535).astype(np.uint16)


os.makedirs('/app/data', exist_ok=True)
os.makedirs('/app/data/flawed', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

# Water mask (circular region, bottom-right quadrant)
yy, xx = np.ogrid[:NROWS, :NCOLS]
water_mask = ((yy - 155)**2 + (xx - 155)**2) < 30**2

# === RED BAND (surface reflectance, float32, 0-1) ===
red = np.full((NROWS, NCOLS), 0.10, dtype=np.float32)
red[10:80, 10:80] = 0.04 + np.random.uniform(0, 0.02, (70, 70)).astype(np.float32)
red[10:80, 120:190] = 0.12 + np.random.uniform(0, 0.04, (70, 70)).astype(np.float32)
red[120:190, 10:80] = 0.07 + np.random.uniform(0, 0.03, (70, 70)).astype(np.float32)
red[water_mask] = 0.05 + np.random.uniform(0, 0.01, water_mask.sum()).astype(np.float32)
# Cloud pixels appear bright in visible bands
red[30:50, 60:85] = 0.80 + np.random.uniform(0, 0.15, (20, 25)).astype(np.float32)

# === NIR BAND (surface reflectance, float32, 0-1) ===
nir = np.full((NROWS, NCOLS), 0.20, dtype=np.float32)
nir[10:80, 10:80] = 0.40 + np.random.uniform(0, 0.10, (70, 70)).astype(np.float32)
nir[10:80, 120:190] = 0.18 + np.random.uniform(0, 0.05, (70, 70)).astype(np.float32)
nir[120:190, 10:80] = 0.30 + np.random.uniform(0, 0.08, (70, 70)).astype(np.float32)
nir[water_mask] = 0.03 + np.random.uniform(0, 0.01, water_mask.sum()).astype(np.float32)
# Cloud pixels bright in NIR
nir[30:50, 60:85] = 0.75 + np.random.uniform(0, 0.15, (20, 25)).astype(np.float32)

# === THERMAL BAND (Level-1 DN, uint16) ===
thermal_bt = np.full((NROWS, NCOLS), 30.0, dtype=np.float32)
thermal_bt[10:80, 10:80] = 24.0 + np.random.uniform(-2, 3, (70, 70)).astype(np.float32)
thermal_bt[10:80, 120:190] = 36.0 + np.random.uniform(-3, 4, (70, 70)).astype(np.float32)
thermal_bt[120:190, 10:80] = 29.0 + np.random.uniform(-2, 3, (70, 70)).astype(np.float32)
thermal_bt[water_mask] = 20.0 + np.random.uniform(-2, 2, water_mask.sum()).astype(np.float32)
# Clouds are cold in thermal
thermal_bt[30:50, 60:85] = -20.0 + np.random.uniform(-5, 5, (20, 25)).astype(np.float32)
# Cloud shadow depresses temperature
thermal_bt[50:65, 75:100] -= 5.0

thermal_dn = bt_to_dn(thermal_bt)

# === QA_PIXEL BAND (bit-packed, uint16) ===
# Landsat Collection 2 Level-1 QA_PIXEL bit layout:
#   Bit 0: Fill
#   Bit 1: Dilated Cloud
#   Bit 2: Cirrus
#   Bit 3: Cloud
#   Bit 4: Cloud Shadow
#   Bit 5: Snow
#   Bit 6: Clear
#   Bit 7: Water
#   Bits 8-9: Cloud Confidence (0=None, 1=Low, 2=Medium, 3=High)
#   Bits 10-11: Cloud Shadow Confidence
#   Bits 12-13: Snow/Ice Confidence
#   Bits 14-15: Cirrus Confidence
qa = np.full((NROWS, NCOLS), 64, dtype=np.uint16)  # Clear land (bit 6)
qa[water_mask] = 192  # Clear + Water (bits 6,7)
qa[30:50, 60:85] = 776   # Cloud(bit3) + CloudConfHigh(bits8-9=11): 8+(3<<8)=776
qa[50:65, 75:100] = 3088  # Shadow(bit4) + ShadowConfHigh(bits10-11=11): 16+(3<<10)=3088
qa[0:3, :] = 1    # Fill (bit 0) - top edge
qa[-3:, :] = 1    # Fill - bottom edge
qa[:, 0:3] = 1    # Fill - left edge
qa[:, -3:] = 1    # Fill - right edge
qa[170:180, 170:180] = 32  # Snow (bit 5)

# === Save GeoTIFFs ===
create_geotiff('/app/data/LC08_B4_RED.tif', red, gdal.GDT_Float32, nodata=-9999.0)
create_geotiff('/app/data/LC08_B5_NIR.tif', nir, gdal.GDT_Float32, nodata=-9999.0)
create_geotiff('/app/data/LC08_B10_THERMAL.tif', thermal_dn, gdal.GDT_UInt16, nodata=0)
create_geotiff('/app/data/LC08_QA_PIXEL.tif', qa, gdal.GDT_UInt16, nodata=1)

# === MTL Metadata ===
mtl = {
    "LANDSAT_METADATA_FILE": {
        "PRODUCT_CONTENTS": {
            "LANDSAT_PRODUCT_ID": "LC08_L1TP_015033_20230715_20230720_02_T1",
            "SPACECRAFT_ID": "LANDSAT_8",
            "SENSOR_ID": "OLI_TIRS",
            "COLLECTION_NUMBER": 2,
            "COLLECTION_CATEGORY": "T1"
        },
        "IMAGE_ATTRIBUTES": {
            "SUN_ELEVATION": 65.34,
            "SUN_AZIMUTH": 135.21,
            "CLOUD_COVER": 12.5,
            "CLOUD_COVER_LAND": 10.2
        },
        "LEVEL1_RADIOMETRIC_RESCALING": {
            "RADIANCE_MULT_BAND_4": 1.2093e-02,
            "RADIANCE_ADD_BAND_4": -60.46517,
            "RADIANCE_MULT_BAND_5": 7.4023e-03,
            "RADIANCE_ADD_BAND_5": -37.01166,
            "RADIANCE_MULT_BAND_10": 3.3420e-04,
            "RADIANCE_ADD_BAND_10": 0.10000
        },
        "LEVEL1_THERMAL_CONSTANTS": {
            "K1_CONSTANT_BAND_10": 774.8853,
            "K2_CONSTANT_BAND_10": 1321.0789
        },
        "PROJECTION_ATTRIBUTES": {
            "MAP_PROJECTION": "UTM",
            "UTM_ZONE": 18,
            "DATUM": "WGS84",
            "ELLIPSOID": "WGS84",
            "GRID_CELL_SIZE_THERMAL": 30.00,
            "GRID_CELL_SIZE_REFLECTIVE": 30.00
        },
        "TIRS_THERMAL_CONSTANTS": {
            "BAND_10_CENTRAL_WAVELENGTH_UM": 10.895
        }
    }
}

with open('/app/data/LC08_MTL.json', 'w') as f:
    json.dump(mtl, f, indent=2)

# === Regions GeoJSON (EPSG:32618 coordinates) ===
regions = {
    "type": "FeatureCollection",
    "crs": {"type": "name", "properties": {"name": "EPSG:32618"}},
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "forest", "id": 1},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [400300, 4497600],
                    [402400, 4497600],
                    [402400, 4499700],
                    [400300, 4499700],
                    [400300, 4497600]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {"name": "urban", "id": 2},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [403600, 4497600],
                    [405700, 4497600],
                    [405700, 4499700],
                    [403600, 4499700],
                    [403600, 4497600]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {"name": "agriculture", "id": 3},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [400300, 4494300],
                    [402400, 4494300],
                    [402400, 4496400],
                    [400300, 4496400],
                    [400300, 4494300]
                ]]
            }
        }
    ]
}

with open('/app/data/regions.geojson', 'w') as f:
    json.dump(regions, f, indent=2)


# ==========================================================================
# Generate FLAWED analysis outputs (for agent to examine and diagnose)
# ==========================================================================

# Flaw 1: Incomplete mask - only checks cloud bit (bit 3), ignores fill/shadow/snow
flawed_mask = (qa & (1 << 3)) == 0

create_geotiff('/app/data/flawed/valid_mask.tif',
               flawed_mask.astype(np.uint8), gdal.GDT_Byte)

# Flaw 2: NDVI computed correctly but with incomplete masking
with np.errstate(divide='ignore', invalid='ignore'):
    flawed_ndvi = ((nir.astype(np.float64) - red.astype(np.float64)) /
                   (nir.astype(np.float64) + red.astype(np.float64)))
flawed_ndvi = flawed_ndvi.astype(np.float32)
flawed_ndvi[~flawed_mask] = np.nan
create_geotiff('/app/data/flawed/ndvi.tif',
               flawed_ndvi, gdal.GDT_Float32, nodata=float('nan'))

# Flaw 3: Spatially uniform emissivity (ignores land cover variation)
flawed_emissivity = np.full((NROWS, NCOLS), 0.97, dtype=np.float32)
flawed_emissivity[~flawed_mask] = np.nan
create_geotiff('/app/data/flawed/emissivity.tif',
               flawed_emissivity, gdal.GDT_Float32, nodata=float('nan'))

# Flaw 4: LST = brightness temperature without emissivity correction
with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
    fl_radiance = M_L * thermal_dn.astype(np.float64) + A_L
    fl_bt_k = K2 / np.log(K1 / fl_radiance + 1)
flawed_lst = (fl_bt_k - 273.15).astype(np.float32)
flawed_lst[~flawed_mask] = np.nan
create_geotiff('/app/data/flawed/lst_celsius.tif',
               flawed_lst, gdal.GDT_Float32, nodata=float('nan'))

# Flaw 5: Zonal statistics computed on flawed data
def pixel_bounds(feat):
    coords = feat['geometry']['coordinates'][0]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    r1 = int((ORIGIN_Y - max(ys)) / PIXEL_SIZE)
    r2 = int((ORIGIN_Y - min(ys)) / PIXEL_SIZE)
    c1 = int((min(xs) - ORIGIN_X) / PIXEL_SIZE)
    c2 = int((max(xs) - ORIGIN_X) / PIXEL_SIZE)
    return max(0, r1), min(NROWS, r2), max(0, c1), min(NCOLS, c2)


flawed_stats = {}
for feat in regions['features']:
    name = feat['properties']['name']
    r1, r2, c1, c2 = pixel_bounds(feat)
    zone = np.zeros((NROWS, NCOLS), dtype=bool)
    zone[r1:r2, c1:c2] = True
    valid_in_zone = zone & flawed_mask & ~np.isnan(flawed_lst)
    if valid_in_zone.sum() > 0:
        zv = flawed_lst[valid_in_zone]
        flawed_stats[name] = {
            "mean_lst_celsius": round(float(np.mean(zv)), 4),
            "min_lst_celsius": round(float(np.min(zv)), 4),
            "max_lst_celsius": round(float(np.max(zv)), 4),
            "valid_pixel_count": int(valid_in_zone.sum()),
        }

with open('/app/data/flawed/zonal_stats.json', 'w') as f:
    json.dump(flawed_stats, f, indent=2)

# Processing notes from the previous analyst
processing_notes = """Landsat 8 LST Processing Notes
Scene: LC08_L1TP_015033_20230715_20230720_02_T1
Date processed: 2023-07-22

Methodology:
- Cloud masking: Extracted cloud flag from QA_PIXEL band to generate pixel validity mask.
- Vegetation index: Standard NDVI computed from red and near-infrared surface reflectance.
- Surface emissivity: Applied literature value of 0.97 (mid-range land surface).
- Thermal processing: Band 10 DN converted to at-sensor radiance via MTL rescaling
  coefficients, then to brightness temperature using inverse Planck equation with
  K1/K2 thermal constants from metadata.
- Temperature output: Brightness temperature converted to Celsius as final LST product.
- Zonal analysis: Mean/min/max statistics computed for each region polygon.

Open items:
- Some edge pixels show unexpected temperature values, possibly instrument artifacts.
- Shadow regions near the cloud patch have normal-looking temperatures despite being shaded.
- Forest zone mean LST seems slightly high relative to expectations, not independently validated.
- Water body temperatures look plausible but emissivity assumption may not hold there.
"""

with open('/app/data/flawed/processing_notes.txt', 'w') as f:
    f.write(processing_notes)


print("Synthetic Landsat 8 scene and flawed analysis generated successfully.")
print(f"  Dimensions: {NROWS}x{NCOLS}, Pixel size: {PIXEL_SIZE}m, CRS: EPSG:{EPSG}")
print(f"  Thermal DN range: {thermal_dn.min()}-{thermal_dn.max()}")
print(f"  QA unique values: {np.unique(qa).tolist()}")
print(f"  Flawed mask valid pixels: {flawed_mask.sum()}")
print(f"  Correct mask valid pixels: {int(((qa & 57) == 0).sum())}")
