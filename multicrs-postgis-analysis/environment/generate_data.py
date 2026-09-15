#!/usr/bin/env python3
"""Generate deterministic synthetic geospatial data for spatial analysis task."""
import random
import json
import csv
import os
import math
from shapely.geometry import Polygon, LineString, mapping
from pyproj import Transformer

random.seed(42)
os.makedirs('/app/data', exist_ok=True)

# Region: Central Europe (roughly Austria/Bavaria/Czech Republic)
LAT_MIN, LAT_MAX = 47.5, 52.5
LON_MIN, LON_MAX = 9.5, 15.5

# CRS transformers (always_xy=True means lon/lat order for geographic CRS)
t_4326_to_32633 = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True)
t_4326_to_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)

# ============================================================
# 1. STATIONS (CSV, WGS84 / EPSG:4326)
# ============================================================
stations = []
for i in range(1, 201):
    lat = LAT_MIN + random.random() * (LAT_MAX - LAT_MIN)
    lon = LON_MIN + random.random() * (LON_MAX - LON_MIN)
    elevation = 150 + random.random() * 1850
    pollutant = 10 + random.random() * 90
    stations.append({
        'id': i,
        'longitude': round(lon, 6),
        'latitude': round(lat, 6),
        'elevation_m': round(elevation, 1),
        'pollutant_reading': round(pollutant, 2)
    })

with open('/app/data/stations.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'id', 'longitude', 'latitude', 'elevation_m', 'pollutant_reading'
    ])
    writer.writeheader()
    writer.writerows(stations)

# ============================================================
# 2. DISTRICTS (GeoJSON with coords in EPSG:32633 / UTM zone 33N)
#    Stored as GeoJSON but coordinates are NOT in WGS84.
#    The metadata.json file documents the actual CRS.
# ============================================================
ROWS, COLS = 4, 3
dlat = (LAT_MAX - LAT_MIN) / ROWS
dlon = (LON_MAX - LON_MIN) / COLS

district_features = []
did = 1
for r in range(ROWS):
    for c in range(COLS):
        y0 = LAT_MIN + r * dlat
        y1 = LAT_MIN + (r + 1) * dlat
        x0 = LON_MIN + c * dlon
        x1 = LON_MIN + (c + 1) * dlon
        corners_4326 = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        corners_32633 = [t_4326_to_32633.transform(x, y) for x, y in corners_4326]
        district_features.append({
            'type': 'Feature',
            'properties': {'district_id': 'D{:02d}'.format(did)},
            'geometry': mapping(Polygon(corners_32633))
        })
        did += 1

with open('/app/data/districts.geojson', 'w') as f:
    json.dump({'type': 'FeatureCollection', 'features': district_features}, f)

# ============================================================
# 3. RIVERS (GeoJSON, WGS84 / EPSG:4326)
# ============================================================
river_paths = [
    [(9.8, 47.8), (10.5, 48.5), (11.2, 49.0), (12.0, 49.5), (13.0, 50.0), (14.0, 50.5)],
    [(9.6, 50.0), (10.5, 50.2), (11.5, 50.1), (12.5, 49.8), (13.5, 49.9), (14.5, 50.3), (15.4, 50.5)],
    [(14.0, 52.3), (14.2, 51.5), (13.8, 50.8), (14.0, 50.0), (14.5, 49.0), (14.8, 48.0)],
    [(10.0, 51.5), (10.5, 51.0), (11.0, 50.5), (11.5, 50.0)],
    [(10.0, 48.5), (11.0, 48.2), (12.0, 48.0), (13.0, 47.8), (14.0, 48.0), (15.0, 48.2)],
]

river_features = []
for idx, path in enumerate(river_paths, 1):
    river_features.append({
        'type': 'Feature',
        'properties': {'river_id': 'R{:02d}'.format(idx), 'name': 'River_{}'.format(idx)},
        'geometry': mapping(LineString(path))
    })

with open('/app/data/rivers.geojson', 'w') as f:
    json.dump({'type': 'FeatureCollection', 'features': river_features}, f)

# ============================================================
# 4. PROTECTED AREAS (GeoJSON with coords in EPSG:3035 / LAEA Europe)
#    Stored as GeoJSON but coordinates are NOT in WGS84.
#    The metadata.json file documents the actual CRS.
# ============================================================
pa_defs = [
    (10.5, 48.5, 0.3),
    (12.0, 50.5, 0.4),
    (14.5, 49.5, 0.35),
    (11.0, 52.0, 0.25),
    (13.5, 48.0, 0.3),
]

pa_features = []
for idx, (cx, cy, radius) in enumerate(pa_defs, 1):
    n_sides = 8
    coords_4326 = []
    for i in range(n_sides):
        angle = 2 * math.pi * i / n_sides
        px = cx + radius * math.cos(angle)
        py = cy + radius * 0.7 * math.sin(angle)
        coords_4326.append((px, py))
    coords_4326.append(coords_4326[0])
    coords_3035 = [t_4326_to_3035.transform(x, y) for x, y in coords_4326]
    pa_features.append({
        'type': 'Feature',
        'properties': {'pa_id': 'PA{:02d}'.format(idx), 'name': 'Protected_Area_{}'.format(idx)},
        'geometry': mapping(Polygon(coords_3035))
    })

with open('/app/data/protected_areas.geojson', 'w') as f:
    json.dump({'type': 'FeatureCollection', 'features': pa_features}, f)

# ============================================================
# 5. METADATA
# ============================================================
metadata = {
    'datasets': {
        'stations.csv': {
            'format': 'CSV',
            'crs': 'EPSG:4326',
            'description': 'Environmental monitoring stations with pollutant readings',
            'coordinate_columns': {'x': 'longitude', 'y': 'latitude'}
        },
        'districts.geojson': {
            'format': 'GeoJSON',
            'crs': 'EPSG:32633',
            'description': 'Administrative district boundaries (WGS 84 / UTM zone 33N). NOTE: coordinates in this file are in EPSG:32633, not WGS84.'
        },
        'rivers.geojson': {
            'format': 'GeoJSON',
            'crs': 'EPSG:4326',
            'description': 'Major river features (WGS 84)'
        },
        'protected_areas.geojson': {
            'format': 'GeoJSON',
            'crs': 'EPSG:3035',
            'description': 'Environmental protection zones (ETRS89-extended / LAEA Europe). NOTE: coordinates in this file are in EPSG:3035, not WGS84.'
        }
    }
}

with open('/app/data/metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

print("Generated: {} stations, {} districts, {} rivers, {} protected areas".format(
    len(stations), len(district_features), len(river_features), len(pa_features)))
