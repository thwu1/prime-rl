#!/usr/bin/env python3
"""Create synthetic GeoTIFF test rasters for the STAC validation task.

Each file uses a different coordinate reference system to test CRS-aware
metadata validation. Files are minimal (10x10 pixels, zero-filled) since
only the geospatial metadata (CRS, extent, band count) matters for testing.
"""

import os
from osgeo import gdal, osr

RASTER_DIR = '/app/rasters'
os.makedirs(RASTER_DIR, exist_ok=True)


def create_raster(filename, srs_def, geotransform, width=10, height=10,
                  bands=1, dtype=gdal.GDT_Float32):
    """Create a minimal GeoTIFF with specified CRS and extent."""
    path = os.path.join(RASTER_DIR, filename)
    drv = gdal.GetDriverByName('GTiff')
    ds = drv.Create(path, width, height, bands, dtype)
    ds.SetGeoTransform(geotransform)

    srs = osr.SpatialReference()
    if isinstance(srs_def, int):
        srs.ImportFromEPSG(srs_def)
    else:
        srs.ImportFromProj4(srs_def)
    ds.SetProjection(srs.ExportToWkt())
    ds = None
    print(f"  Created {path}")


# 1. Global SST — EPSG:4326 (WGS84 geographic)
#    Extent: W=-180, S=-60, E=180, N=60
create_raster('global_sst.tif', 4326,
              (-180.0, 36.0, 0.0, 60.0, 0.0, -12.0),
              bands=1)

# 2. Landsat California — EPSG:32611 (UTM Zone 11N)
#    Extent in UTM meters: UL=(480000, 3870000), LR=(580000, 3770000)
create_raster('landsat_california.tif', 32611,
              (480000.0, 10000.0, 0.0, 3870000.0, 0.0, -10000.0),
              bands=6, dtype=gdal.GDT_UInt16)

# 3. Greenland Ice — EPSG:3413 (NSIDC Sea Ice Polar Stereographic North)
#    Extent in PS meters: UL=(-600000, -1000000), LR=(-100000, -1500000)
create_raster('greenland_ice.tif', 3413,
              (-600000.0, 50000.0, 0.0, -1000000.0, 0.0, -50000.0),
              bands=1)

# 4. MODIS Sinusoidal — custom sinusoidal projection (no standard EPSG code)
#    Tile approximately h26 (South/Southeast Asia region)
create_raster('modis_sinusoidal.tif',
              '+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs',
              (8895604.157, 100000.0, 0.0, 2223901.039, 0.0, -100000.0),
              bands=2)

# 5. Sentinel-1 SAR — EPSG:32633 (UTM Zone 33N)
#    Extent in UTM meters: UL=(400000, 7100000), LR=(500000, 7000000)
create_raster('sentinel1_sar.tif', 32633,
              (400000.0, 10000.0, 0.0, 7100000.0, 0.0, -10000.0),
              bands=2)

# 6. Antarctic Ice — EPSG:3031 (Antarctic Polar Stereographic)
#    Extent in PS meters: UL=(-1500000, 500000), LR=(-500000, -500000)
create_raster('antarctic_ice.tif', 3031,
              (-1500000.0, 100000.0, 0.0, 500000.0, 0.0, -100000.0),
              bands=2)

print("All rasters created successfully.")
