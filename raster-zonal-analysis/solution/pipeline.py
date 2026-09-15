#!/usr/bin/env python3
"""Reference solution for spectral band identification and geospatial analysis."""

import numpy as np
import json
import csv
import os
import rasterio
from rasterio.features import geometry_mask
from pyproj import Transformer
from shapely.geometry import Polygon, Point, box as shapely_box
from shapely import make_valid
from scipy.ndimage import map_coordinates

# ==== Step 1: Explore and characterize data ====
print("=== Exploring /app/data/ ===")
for fname in sorted(os.listdir('/app/data')):
    print(f"  {fname}")

# ---- Load raster ----
with rasterio.open('/app/data/imagery.tif') as src:
    data = src.read()  # (4, H, W)
    transform = src.transform
    H, W = src.height, src.width
    raster_crs = src.crs
    nodata_meta = src.nodata

print(f"\nRaster: {H}x{W}, {data.shape[0]} bands, CRS={raster_crs}, nodata={nodata_meta}")

# ==== Step 2: Diagnose data quality issues ====
print("\n=== Data quality diagnosis ===")

# Check nodata metadata vs actual data
has_nodata_pixels = (data == nodata_meta).any()
print(f"Pixels matching nodata={nodata_meta}: {has_nodata_pixels}")

# Check for NaN corruption
for b in range(4):
    nan_count = int(np.isnan(data[b]).sum())
    if nan_count > 0:
        print(f"Band {b}: {nan_count} NaN pixels (sensor corruption)")

nan_mask = np.zeros((H, W), dtype=bool)
for b in range(4):
    nan_mask |= np.isnan(data[b])
print(f"Total NaN-affected pixels: {int(nan_mask.sum())}")

# ==== Step 3: Identify spectral bands ====
print("\n=== Band identification (radiometric analysis) ===")
band_means = {}
for b in range(4):
    mean_val = float(np.nanmean(data[b]))
    std_val = float(np.nanstd(data[b]))
    band_means[b] = mean_val
    print(f"Band {b}: mean={mean_val:.1f}, std={std_val:.1f}")

# Sort by mean reflectance for a vegetation-dominant mixed scene:
# Blue (lowest) < Red < Green < NIR (highest)
sorted_bands = sorted(band_means.keys(), key=lambda b: band_means[b])
blue_idx = sorted_bands[0]
red_idx = sorted_bands[1]
green_idx = sorted_bands[2]
nir_idx = sorted_bands[3]

band_mapping = {"red": int(red_idx), "green": int(green_idx),
                "blue": int(blue_idx), "nir": int(nir_idx)}
print(f"\nIdentified band mapping: {band_mapping}")

# ==== Step 4: Compute spectral indices ====
nir = data[nir_idx].astype(np.float64)
red = data[red_idx].astype(np.float64)
green = data[green_idx].astype(np.float64)

with np.errstate(invalid='ignore', divide='ignore'):
    ndvi = (nir - red) / (nir + red)
    ndwi = (green - nir) / (green + nir)

ndvi[nan_mask] = np.nan
ndwi[nan_mask] = np.nan

# ==== Step 5: Load and process zones ====
ox, oy = transform.c, transform.f
px, py = transform.a, -transform.e
t = Transformer.from_crs("EPSG:4326", "EPSG:32617", always_xy=True)

with open('/app/data/zones.geojson') as f:
    zones_gj = json.load(f)

zones = []
for feat in zones_gj['features']:
    zid = feat['properties']['zone_id']
    coords = feat['geometry']['coordinates'][0]
    utm_coords = [t.transform(lon, lat) for lon, lat in coords]
    geom = Polygon(utm_coords)
    if not geom.is_valid:
        print(f"\nZone {zid}: invalid geometry detected, repairing with make_valid()")
        geom = make_valid(geom)
        print(f"  Repaired: {geom.geom_type}, area={geom.area:.0f} m^2")
    zones.append({'zone_id': zid, 'geom': geom})
zones.sort(key=lambda z: z['zone_id'])

# ==== Step 6: Zonal statistics ====
raster_box = shapely_box(ox, oy - H * py, ox + W * px, oy)

zonal_stats = []
for zone in zones:
    clipped = zone['geom'].intersection(raster_box)
    if clipped.is_empty:
        continue

    mask = geometry_mask([clipped], out_shape=(H, W),
                         transform=transform, invert=True)
    valid_mask = mask & ~nan_mask
    ndvi_vals = ndvi[valid_mask]
    ndwi_vals = ndwi[valid_mask]

    zonal_stats.append({
        'zone_id': zone['zone_id'],
        'ndvi_mean': round(float(np.mean(ndvi_vals)), 6),
        'ndvi_std': round(float(np.std(ndvi_vals)), 6),
        'ndvi_median': round(float(np.median(ndvi_vals)), 6),
        'ndwi_mean': round(float(np.mean(ndwi_vals)), 6),
        'ndwi_std': round(float(np.std(ndwi_vals)), 6),
        'ndwi_median': round(float(np.median(ndwi_vals)), 6),
        'valid_pixels': int(np.sum(valid_mask)),
    })
zonal_stats.sort(key=lambda z: z['zone_id'])

# ==== Step 7: Station analysis ====
# Read CSV — coordinates are UTM (recognized from magnitude matching raster extent)
print("\n=== Station coordinate analysis ===")
stations = []
with open('/app/data/samples.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        stations.append({
            'station_id': int(row['id']),
            'x': float(row['x']),
            'y': float(row['y']),
        })
stations.sort(key=lambda s: s['station_id'])

x_range = (min(s['x'] for s in stations), max(s['x'] for s in stations))
y_range = (min(s['y'] for s in stations), max(s['y'] for s in stations))
print(f"Station x range: {x_range} (raster: {ox}-{ox + W * px})")
print(f"Station y range: {y_range} (raster: {oy - H * py}-{oy})")
print("Coordinates match raster UTM extent -> using as EPSG:32617 directly")

station_results = []
for st in stations:
    col = (st['x'] - ox) / px - 0.5
    row = (oy - st['y']) / py - 0.5

    nir_val = float(map_coordinates(data[nir_idx].astype(np.float64),
                                     [[row], [col]], order=1, mode='nearest')[0])
    red_val = float(map_coordinates(data[red_idx].astype(np.float64),
                                     [[row], [col]], order=1, mode='nearest')[0])
    green_val = float(map_coordinates(data[green_idx].astype(np.float64),
                                      [[row], [col]], order=1, mode='nearest')[0])

    ndvi_i = (nir_val - red_val) / (nir_val + red_val)
    ndwi_i = (green_val - nir_val) / (green_val + nir_val)

    pt = Point(st['x'], st['y'])
    zone_id = None
    for zone in zones:
        if zone['geom'].contains(pt):
            zone_id = zone['zone_id']
            break

    station_results.append({
        'station_id': st['station_id'],
        'zone_id': zone_id,
        'ndvi': round(ndvi_i, 6),
        'ndwi': round(ndwi_i, 6),
    })
station_results.sort(key=lambda s: s['station_id'])

# ==== Step 8: Correlation ====
zone_means = {z['zone_id']: (z['ndvi_mean'], z['ndwi_mean']) for z in zonal_stats}
st_ndvi, zm_ndvi, st_ndwi, zm_ndwi = [], [], [], []
for sr in station_results:
    zid = sr['zone_id']
    if zid in zone_means:
        st_ndvi.append(sr['ndvi'])
        zm_ndvi.append(zone_means[zid][0])
        st_ndwi.append(sr['ndwi'])
        zm_ndwi.append(zone_means[zid][1])

ndvi_r = float(np.corrcoef(st_ndvi, zm_ndvi)[0, 1])
ndwi_r = float(np.corrcoef(st_ndwi, zm_ndwi)[0, 1])

# ==== Write outputs ====
os.makedirs('/app/output', exist_ok=True)

with open('/app/output/band_mapping.json', 'w') as f:
    json.dump(band_mapping, f, indent=2)

with open('/app/output/zonal_stats.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'zone_id', 'ndvi_mean', 'ndvi_std', 'ndvi_median',
        'ndwi_mean', 'ndwi_std', 'ndwi_median', 'valid_pixels'])
    writer.writeheader()
    writer.writerows(zonal_stats)

with open('/app/output/station_values.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'station_id', 'zone_id', 'ndvi', 'ndwi'])
    writer.writeheader()
    writer.writerows(station_results)

with open('/app/output/correlation.json', 'w') as f:
    json.dump({
        'ndvi_pearson_r': round(ndvi_r, 6),
        'ndwi_pearson_r': round(ndwi_r, 6),
    }, f, indent=2)

print("\n=== Pipeline complete. Outputs written to /app/output/ ===")
