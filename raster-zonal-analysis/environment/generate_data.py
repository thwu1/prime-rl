#!/usr/bin/env python3
"""Generate geospatial data with diagnostic challenges for spectral band identification."""
import numpy as np
import json
import os
import csv

np.random.seed(42)
H, W = 200, 200
OX, OY, PS = 500000.0, 4500000.0, 10.0  # UTM Zone 17N origin and pixel size

os.makedirs('/app/data', exist_ok=True)

# --- Spatial patterns (normalized 0-1) ---
yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
veg = np.clip(
    0.5 + 0.3 * np.sin(xx * np.pi / 60) * np.cos(yy * np.pi / 50)
    + 0.25 * np.exp(-((xx - 160)**2 + (yy - 30)**2) / 1500), 0, 1)
wat = np.clip(
    0.25 * np.exp(-((xx - 30)**2 + (yy - 170)**2) / 1200)
    + 0.05 * np.sin(xx * np.pi / 40), 0, 1)
urb = np.clip(
    0.4 * np.exp(-((xx - 90)**2 + (yy - 80)**2) / 2500), 0, 1)
noise = np.random.rand(H, W) * 0.03

# --- Bands stored in SHUFFLED order: [NIR, Blue, Red, Green] ---
# Correct mapping: band0=NIR, band1=Blue, band2=Red, band3=Green
nir_arr = np.clip(veg * 5000 + urb * 800 + wat * 80 + 400 + noise * 400,
                  50, 10000).astype(np.float32)
blue_arr = np.clip(urb * 1400 + wat * 600 + veg * 200 + 250 + noise * 400,
                   50, 10000).astype(np.float32)
red_arr = np.clip(urb * 2000 + veg * 500 + wat * 150 + 200 + noise * 400,
                  50, 10000).astype(np.float32)
green_arr = np.clip(veg * 900 + urb * 1500 + wat * 400 + 300 + noise * 400,
                    50, 10000).astype(np.float32)

data = np.stack([nir_arr, blue_arr, red_arr, green_arr])

# Introduce NaN corruption in band 2 (Red), rows 98-102
# This simulates sensor scan-line failure NOT captured by nodata metadata
data[2, 98:103, :] = np.nan

import rasterio
from rasterio.transform import from_origin
from rasterio.crs import CRS

transform = from_origin(OX, OY, PS, PS)
crs = CRS.from_epsg(32617)

# nodata set to -9999 but no pixels actually have this value (misleading metadata)
with rasterio.open('/app/data/imagery.tif', 'w', driver='GTiff',
                   height=H, width=W, count=4, dtype='float32',
                   crs=crs, transform=transform, nodata=-9999.0) as dst:
    dst.write(data)

# --- Zones: 6 polygons in WGS84 ---
from pyproj import Transformer
t2g = Transformer.from_crs("EPSG:32617", "EPSG:4326", always_xy=True)

# Regular rectangular zones
rect_zones = [
    (1, 501200, 4499100, 501950, 4499600),
    (2, 500350, 4498850, 501150, 4499550),
    (4, 501700, 4499650, 502300, 4500300),  # Partially outside raster
    (5, 501150, 4498700, 501300, 4498850),
    (6, 501200, 4498050, 501950, 4498700),
]

features = []
for zid, x0, y0, x1, y1 in rect_zones:
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    coords = [list(t2g.transform(x, y)) for x, y in corners]
    features.append({
        "type": "Feature",
        "properties": {"zone_id": zid},
        "geometry": {"type": "Polygon", "coordinates": [coords]}
    })

# Zone 3: bowtie (self-intersecting) polygon — edges cross at center
# Vertices traverse: bottom-left -> top-right -> bottom-right -> top-left -> close
z3_bowtie_utm = [
    (500050, 4498050),
    (500750, 4498750),
    (500750, 4498050),
    (500050, 4498750),
    (500050, 4498050),
]
z3_coords = [list(t2g.transform(x, y)) for x, y in z3_bowtie_utm]
features.append({
    "type": "Feature",
    "properties": {"zone_id": 3},
    "geometry": {"type": "Polygon", "coordinates": [z3_coords]}
})

with open('/app/data/zones.geojson', 'w') as f:
    json.dump({"type": "FeatureCollection", "features": features}, f, indent=2)

# --- Samples: CSV with UTM coordinates (CRS NOT documented anywhere) ---
# The solver must recognize these as UTM from the coordinate magnitudes
stations_data = [
    (1, 501500, 4499400),
    (2, 501400, 4499500),
    (3, 501750, 4499300),
    (4, 500700, 4499300),
    (5, 500500, 4499100),
    (6, 500900, 4499400),
    (7, 500250, 4498450),   # Inside zone 3 left triangle (after repair)
    (8, 500550, 4498300),   # Inside zone 3 right triangle (after repair)
    (9, 500200, 4498550),   # Inside zone 3 left triangle (after repair)
    (10, 501850, 4499850),  # Zone 4 (inside raster portion)
    (11, 501750, 4499750),  # Zone 4
    (12, 501200, 4498800),  # Zone 5
    (13, 501250, 4498750),  # Zone 5
    (14, 501500, 4498400),  # Zone 6
    (15, 501700, 4498200),  # Zone 6
]

np.random.seed(99)
with open('/app/data/samples.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['id', 'x', 'y', 'chlorophyll_ugL'])
    for sid, sx, sy in stations_data:
        chl = round(15.0 + np.random.rand() * 30.0, 2)
        writer.writerow([sid, sx, sy, chl])

# --- Metadata (intentionally incomplete) ---
with open('/app/data/metadata.json', 'w') as f:
    json.dump({
        "project": "Wetland Monitoring Survey - Q3 2024",
        "sensor": "Multispectral UAV Platform",
        "acquisition_date": "2024-08-15",
        "bands": ["band_0", "band_1", "band_2", "band_3"],
        "band_wavelengths_nm": None,
        "notes": "Band order metadata corrupted during GeoTIFF conversion. Original calibration report missing.",
        "raster_file": "imagery.tif",
        "zone_boundaries": "zones.geojson",
        "sample_locations": "samples.csv"
    }, f, indent=2)

print("Generated: imagery.tif (4 bands, EPSG:32617, 10m, shuffled band order, NaN corruption in band 2)")
print("Generated: zones.geojson (6 polygons, EPSG:4326, zone 3 self-intersecting)")
print("Generated: samples.csv (15 points, UTM coords, no CRS documented)")
print("Generated: metadata.json")
