#!/usr/bin/env python3
"""Generate synthetic terrain data with hidden quality issues for the
terrain suitability assessment task.

"""
import json
import os
import numpy as np
from osgeo import gdal, osr, ogr

OUT_DIR = os.environ.get('TASK_DATA_DIR', '/opt/task_data')
os.makedirs(OUT_DIR, exist_ok=True)

# ---- DEM parameters ----
NX, NY = 300, 300
PIXEL_SIZE = 30.0  # meters
ORIGIN_E = 500000.0  # UTM easting (left edge)
ORIGIN_N = 4509000.0  # UTM northing (top edge, north-up raster)
EPSG_UTM = 32633

# ---- Hidden quality issue #1: vertical datum bias ----
VERTICAL_BIAS = 47.2  # meters — simulates geoid/ellipsoid mismatch

# ---- Create deterministic terrain (pure formula, no randomness) ----
x = np.linspace(0, 9, NX)
y = np.linspace(0, 9, NY)
X, Y = np.meshgrid(x, y)

Z_true = (500.0
          + 200.0 * np.sin(X * 0.5) * np.cos(Y * 0.6)
          + 150.0 * np.exp(-((X - 3.0)**2 + (Y - 4.0)**2) / 3.0)
          + 100.0 * np.exp(-((X - 7.0)**2 + (Y - 2.0)**2) / 2.0)
          - 80.0 * np.exp(-((X - 5.0)**2 + (Y - 7.0)**2) / 4.0)
          + 60.0 * np.sin(X * 1.5) * np.sin(Y * 1.8)
          + 40.0 * np.cos((X + Y) * 0.9))

# Apply vertical bias
Z_biased = (Z_true + VERTICAL_BIAS).astype(np.float32)

# ---- Hidden quality issue #2: nodata contamination ----
# Scatter -9999 values WITHOUT setting nodata metadata
nodata_pixels = [
    (45, 120), (46, 121), (47, 120),
    (100, 200), (101, 200),
    (150, 80), (151, 80), (150, 81),
    (200, 150),
    (80, 250), (81, 250), (80, 251),
    (250, 100),
    (180, 60),
]
for r, c in nodata_pixels:
    Z_biased[r, c] = -9999.0

# ---- Write DEM WITHOUT nodata metadata ----
dem_path = os.path.join(OUT_DIR, 'dem.tif')
driver = gdal.GetDriverByName('GTiff')
ds = driver.Create(dem_path, NX, NY, 1, gdal.GDT_Float32)
ds.SetGeoTransform([ORIGIN_E, PIXEL_SIZE, 0, ORIGIN_N, 0, -PIXEL_SIZE])
srs = osr.SpatialReference()
srs.ImportFromEPSG(EPSG_UTM)
ds.SetProjection(srs.ExportToWkt())
band = ds.GetRasterBand(1)
band.WriteArray(Z_biased)
# Deliberately NOT calling band.SetNoDataValue()
band.FlushCache()
ds = None

# ---- Generate ground control points with TRUE (unbiased) elevations ----
control_positions = [
    (20, 20), (20, 150), (20, 280),
    (60, 50), (60, 200),
    (100, 30), (100, 150), (100, 270),
    (140, 80), (140, 220),
    (180, 40), (180, 160), (180, 260),
    (220, 70), (220, 200),
    (260, 30), (260, 140), (260, 270),
    (280, 100), (280, 250),
]
nodata_set = set(nodata_pixels)

csv_path = os.path.join(OUT_DIR, 'control_points.csv')
with open(csv_path, 'w') as f:
    f.write('id,easting,northing,elevation_m\n')
    for i, (r, c) in enumerate(control_positions):
        assert (r, c) not in nodata_set
        easting = ORIGIN_E + c * PIXEL_SIZE + PIXEL_SIZE / 2.0
        northing = ORIGIN_N - r * PIXEL_SIZE - PIXEL_SIZE / 2.0
        true_elev = float(Z_true[r, c])
        f.write('{},{:.2f},{:.2f},{:.2f}\n'.format(
            i + 1, easting, northing, true_elev))

# ---- Hidden quality issue #3: lat/lon swap in exclusion zones ----
srs_utm = osr.SpatialReference()
srs_utm.ImportFromEPSG(EPSG_UTM)
srs_utm.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
srs_wgs = osr.SpatialReference()
srs_wgs.ImportFromEPSG(4326)
srs_wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
ct = osr.CoordinateTransformation(srs_utm, srs_wgs)

exclusion_utm = [
    (503000.0, 4505000.0),
    (506000.0, 4502000.0),
    (501500.0, 4507000.0),
]

features = []
for i, (e, n) in enumerate(exclusion_utm):
    pt = ogr.Geometry(ogr.wkbPoint)
    pt.AddPoint(e, n)
    pt.Transform(ct)
    lon, lat = pt.GetX(), pt.GetY()
    # DELIBERATELY store as [lat, lon] instead of GeoJSON-standard [lon, lat]
    features.append({
        "type": "Feature",
        "properties": {"id": i + 1, "name": "restricted_zone_{}".format(i + 1)},
        "geometry": {
            "type": "Point",
            "coordinates": [round(lat, 6), round(lon, 6)]
        }
    })

geojson = {"type": "FeatureCollection", "features": features}
geojson_path = os.path.join(OUT_DIR, 'exclusion_zones.geojson')
with open(geojson_path, 'w') as f:
    json.dump(geojson, f, indent=2)

# ---- Site specification (parameters only, no algorithm guidance) ----
spec = {
    "slope_range_deg": [1.5, 12.0],
    "aspect_range_deg": [135.0, 225.0],
    "elevation_range_m": [300.0, 750.0],
    "max_terrain_ruggedness_index": 8.0,
    "min_contiguous_area_m2": 50000,
    "edge_buffer_pixels": 5,
    "exclusion_buffer_m": 500.0,
    "connectivity": 8,
    "scoring": {
        "normalization": "min_max",
        "tie_value": 0.5,
        "weights": {
            "area_m2": 0.35,
            "mean_elevation": 0.25,
            "mean_slope": -0.15,
            "aspect_uniformity": 0.25
        },
        "report_top_n": 5
    }
}

spec_path = os.path.join(OUT_DIR, 'site_spec.json')
with open(spec_path, 'w') as f:
    json.dump(spec, f, indent=2)

# Verify all files were created
for name in ['dem.tif', 'control_points.csv', 'exclusion_zones.geojson', 'site_spec.json']:
    fpath = os.path.join(OUT_DIR, name)
    assert os.path.isfile(fpath), f"Failed to create {fpath}"
    assert os.path.getsize(fpath) > 0, f"Empty file: {fpath}"

print("Task data generated in {}".format(OUT_DIR))
print("DEM shape: {}x{}, pixel size: {}m".format(NY, NX, PIXEL_SIZE))
print("Files: dem.tif, control_points.csv, exclusion_zones.geojson, site_spec.json")
