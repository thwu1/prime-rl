#!/usr/bin/env python3
"""Generate synthetic satellite data for the geospatial pipeline task."""
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from pyproj import Transformer
import json
import os


def main():
    rng = np.random.default_rng(42)

    # Raster parameters
    W, H = 300, 300
    ps = 30.0  # pixel size in meters
    x0, y0 = 400000.0, 5809000.0  # top-left in UTM 33N
    nodata = -9999.0
    epsg = 32633
    transform = Affine(ps, 0.0, x0, 0.0, -ps, y0)

    # Generate 6 bands: Coastal, Blue, Green, Red, RedEdge, NIR
    # Values in surface reflectance * 10000 scale (Sentinel-2 L2A convention)
    bands = {
        'coastal':  rng.uniform(200,  1500, (H, W)).astype(np.float32),
        'blue':     rng.uniform(300,  2000, (H, W)).astype(np.float32),
        'green':    rng.uniform(400,  2500, (H, W)).astype(np.float32),
        'red':      rng.uniform(300,  3000, (H, W)).astype(np.float32),
        'rededge':  rng.uniform(500,  4000, (H, W)).astype(np.float32),
        'nir':      rng.uniform(800,  6000, (H, W)).astype(np.float32),
    }

    # --- Nodata regions (clouds + scan-line gap) ---
    yy, xx = np.mgrid[:H, :W]
    cloud1 = (((yy - 60) / 25.0) ** 2 + ((xx - 70) / 30.0) ** 2) <= 1.0
    cloud2 = ((yy - 230) ** 2 + (xx - 250) ** 2) <= 40 ** 2
    scanline = (yy >= 150) & (yy < 155)
    nodata_mask = cloud1 | cloud2 | scanline

    for b in bands.values():
        b[nodata_mask] = nodata

    # --- Water body (low NIR, moderate visible) ---
    water = (yy >= 170) & (yy < 210) & (xx >= 90) & (xx < 150)
    water_valid = water & ~nodata_mask
    rng_w = np.random.default_rng(100)
    nw = int(water_valid.sum())
    bands['coastal'][water_valid]  = rng_w.uniform(1200, 2000, nw).astype(np.float32)
    bands['blue'][water_valid]     = rng_w.uniform(600,  1200, nw).astype(np.float32)
    bands['green'][water_valid]    = rng_w.uniform(900,  1500, nw).astype(np.float32)
    bands['red'][water_valid]      = rng_w.uniform(100,  400,  nw).astype(np.float32)
    bands['rededge'][water_valid]  = rng_w.uniform(50,   200,  nw).astype(np.float32)
    bands['nir'][water_valid]      = rng_w.uniform(20,   100,  nw).astype(np.float32)

    # --- Division-by-zero hazard pixels (valid data, but Red=NIR=Green=RedEdge=0) ---
    for r, c in [(100, 100), (100, 101), (100, 102)]:
        if not nodata_mask[r, c]:
            bands['red'][r, c]     = 0.0
            bands['nir'][r, c]     = 0.0
            bands['green'][r, c]   = 0.0
            bands['rededge'][r, c] = 0.0

    # --- Dense vegetation area (high NIR, low Red) ---
    veg = (yy >= 20) & (yy < 80) & (xx >= 180) & (xx < 260)
    veg_valid = veg & ~nodata_mask
    rng_v = np.random.default_rng(200)
    nv = int(veg_valid.sum())
    bands['red'][veg_valid]     = rng_v.uniform(200,  500,  nv).astype(np.float32)
    bands['nir'][veg_valid]     = rng_v.uniform(4000, 5500, nv).astype(np.float32)
    bands['rededge'][veg_valid] = rng_v.uniform(2000, 3500, nv).astype(np.float32)
    bands['green'][veg_valid]   = rng_v.uniform(800,  1500, nv).astype(np.float32)

    # --- Write raster ---
    data = np.stack([bands['coastal'], bands['blue'], bands['green'],
                     bands['red'], bands['rededge'], bands['nir']])

    os.makedirs('/app/data', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    profile = {
        'driver': 'GTiff',
        'dtype': 'float32',
        'width': W,
        'height': H,
        'count': 6,
        'crs': CRS.from_epsg(epsg),
        'transform': transform,
        'nodata': nodata,
        'compress': 'deflate',
    }

    with rasterio.open('/app/data/multiband.tif', 'w', **profile) as dst:
        dst.write(data)
        for i, name in enumerate(['Coastal', 'Blue', 'Green', 'Red', 'RedEdge', 'NIR'], 1):
            dst.set_band_description(i, name)

    # --- Zone polygons in EPSG:4326 ---
    tr = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)

    def utm_box_to_geojson(xmin, ymin, xmax, ymax):
        n = 20
        coords = []
        for i in range(n):
            x = xmin + (xmax - xmin) * i / n
            lon, lat = tr.transform(x, ymin)
            coords.append([lon, lat])
        for i in range(n):
            y = ymin + (ymax - ymin) * i / n
            lon, lat = tr.transform(xmax, y)
            coords.append([lon, lat])
        for i in range(n):
            x = xmax - (xmax - xmin) * i / n
            lon, lat = tr.transform(x, ymax)
            coords.append([lon, lat])
        for i in range(n):
            y = ymax - (ymax - ymin) * i / n
            lon, lat = tr.transform(xmin, y)
            coords.append([lon, lat])
        coords.append(coords[0])
        return {"type": "Polygon", "coordinates": [coords]}

    zones = [
        (1, "Forest",      utm_box_to_geojson(405000, 5806000, 408000, 5808500)),
        (2, "Lake",         utm_box_to_geojson(402500, 5802500, 404500, 5803500)),
        (3, "Mixed",        utm_box_to_geojson(401500, 5806500, 403500, 5808000)),
        (4, "Agriculture",  utm_box_to_geojson(404000, 5803000, 407000, 5806000)),
        (5, "Edge",         utm_box_to_geojson(407000, 5804000, 411000, 5807000)),
    ]

    features = []
    for zid, name, geom in zones:
        features.append({
            "type": "Feature",
            "id": str(zid),
            "properties": {"zone_id": zid, "zone_name": name},
            "geometry": geom,
        })

    geojson = {"type": "FeatureCollection", "features": features}
    with open('/app/data/zones.geojson', 'w') as f:
        json.dump(geojson, f, indent=2)

    # --- Analysis configuration ---
    config = {
        "band_names": {
            "b1": "Coastal", "b2": "Blue", "b3": "Green",
            "b4": "Red", "b5": "RedEdge", "b6": "NIR",
        },
        "indices": {
            "NDVI": {
                "formula": "(b6 - b4) / (b6 + b4)",
                "description": "Normalized Difference Vegetation Index",
                "valid_range": [-1.0, 1.0],
            },
            "NDWI": {
                "formula": "(b3 - b6) / (b3 + b6)",
                "description": "Normalized Difference Water Index",
                "valid_range": [-1.0, 1.0],
            },
            "EVI": {
                "formula": "2.5 * (b6 - b4) / (b6 + 6.0 * b4 - 7.5 * b2 + 10000.0)",
                "description": "Enhanced Vegetation Index",
                "valid_range": [-1.0, 1.0],
            },
            "SAVI": {
                "formula": "1.5 * (b6 - b4) / (b6 + b4 + 5000.0)",
                "description": "Soil Adjusted Vegetation Index",
                "valid_range": [-1.0, 1.0],
            },
            "NDRE": {
                "formula": "(b6 - b5) / (b6 + b5)",
                "description": "Normalized Difference Red Edge Index",
                "valid_range": [-1.0, 1.0],
            },
        },
        "output_crs": "EPSG:32633",
        "output_nodata": -9999.0,
        "cog_options": {
            "blocksize": 256,
            "overview_factors": [2, 4, 8],
            "overview_resampling": "average",
        },
        "statistics": ["mean", "std", "min", "max", "median", "count"],
        "division_by_zero_threshold": 1e-10,
    }
    with open('/app/data/analysis_config.json', 'w') as f:
        json.dump(config, f, indent=2)

    print("Data generated successfully.")
    print(f"  Raster: /app/data/multiband.tif ({W}x{H}, 6 bands, EPSG:{epsg})")
    print(f"  Zones:  /app/data/zones.geojson (5 zones, EPSG:4326)")
    print(f"  Config: /app/data/analysis_config.json (5 spectral indices)")


if __name__ == '__main__':
    main()
