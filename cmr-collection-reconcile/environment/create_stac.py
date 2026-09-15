#!/usr/bin/env python3
"""Generate STAC Item JSON files with deliberate metadata errors.

Errors injected:
  1. global_sst        — temporal:  start_datetime > end_datetime (swapped)
  2. landsat_california — spatial:   bbox in UTM meters, not WGS84 degrees
  3. greenland_ice      — spatial:   bbox longitude signs inverted
  4. modis_sinusoidal   — spatial:   bbox in sinusoidal meters, not WGS84
  5. sentinel1_sar      — CRS:      proj:epsg=32632 (file is 32633)
  6. sentinel1_sar      — spatial:   bbox computed from wrong UTM zone
  7. antarctic_ice      — band_count: eo:bands lists 3 bands, file has 2
"""

import json
import os
from osgeo import gdal, osr

RASTER_DIR = '/app/rasters'
STAC_DIR = '/app/stac_items'
os.makedirs(STAC_DIR, exist_ok=True)


def compute_wgs84_bbox(ds):
    """Transform raster extent to WGS84 bounding box."""
    gt = ds.GetGeoTransform()
    w, h = ds.RasterXSize, ds.RasterYSize
    ulx, uly = gt[0], gt[3]
    lrx = ulx + w * gt[1]
    lry = uly + h * gt[5]

    src_srs = osr.SpatialReference()
    src_srs.ImportFromWkt(ds.GetProjection())
    src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    tgt_srs = osr.SpatialReference()
    tgt_srs.ImportFromEPSG(4326)
    tgt_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    ct = osr.CoordinateTransformation(src_srs, tgt_srs)

    points = [
        (ulx, uly), (lrx, uly), (lrx, lry), (ulx, lry),
        ((ulx + lrx) / 2, uly), ((ulx + lrx) / 2, lry),
        (ulx, (uly + lry) / 2), (lrx, (uly + lry) / 2),
    ]
    lons, lats = [], []
    for x, y in points:
        lon, lat, _ = ct.TransformPoint(x, y)
        lons.append(lon)
        lats.append(lat)

    return [round(min(lons), 6), round(min(lats), 6),
            round(max(lons), 6), round(max(lats), 6)]


def compute_bbox_wrong_crs(ds, wrong_epsg):
    """Compute WGS84 bbox interpreting raster coords under a wrong CRS."""
    gt = ds.GetGeoTransform()
    w, h = ds.RasterXSize, ds.RasterYSize
    ulx, uly = gt[0], gt[3]
    lrx = ulx + w * gt[1]
    lry = uly + h * gt[5]

    wrong_srs = osr.SpatialReference()
    wrong_srs.ImportFromEPSG(wrong_epsg)
    wrong_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    tgt_srs = osr.SpatialReference()
    tgt_srs.ImportFromEPSG(4326)
    tgt_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    ct = osr.CoordinateTransformation(wrong_srs, tgt_srs)

    points = [
        (ulx, uly), (lrx, uly), (lrx, lry), (ulx, lry),
        ((ulx + lrx) / 2, uly), ((ulx + lrx) / 2, lry),
        (ulx, (uly + lry) / 2), (lrx, (uly + lry) / 2),
    ]
    lons, lats = [], []
    for x, y in points:
        lon, lat, _ = ct.TransformPoint(x, y)
        lons.append(lon)
        lats.append(lat)

    return [round(min(lons), 6), round(min(lats), 6),
            round(max(lons), 6), round(max(lats), 6)]


def get_native_extent(ds):
    """Get raster extent in native CRS coordinates."""
    gt = ds.GetGeoTransform()
    w, h = ds.RasterXSize, ds.RasterYSize
    ulx, uly = gt[0], gt[3]
    lrx = ulx + w * gt[1]
    lry = uly + h * gt[5]
    return [round(min(ulx, lrx), 6), round(min(uly, lry), 6),
            round(max(ulx, lrx), 6), round(max(uly, lry), 6)]


def geojson_polygon(bbox):
    w, s, e, n = bbox
    return {
        "type": "Polygon",
        "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]
    }


def write_item(name, item):
    path = os.path.join(STAC_DIR, f'{name}.json')
    with open(path, 'w') as f:
        json.dump(item, f, indent=2)
    print(f"  Created {path}")


# ── 1. global_sst — ERROR: temporal dates swapped ──────────────────────────
ds = gdal.Open(os.path.join(RASTER_DIR, 'global_sst.tif'))
bbox = compute_wgs84_bbox(ds)
write_item('global_sst', {
    "type": "Feature",
    "stac_version": "1.0.0",
    "stac_extensions": [
        "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
        "https://stac-extensions.github.io/eo/v1.1.0/schema.json"
    ],
    "id": "global_sst",
    "geometry": geojson_polygon(bbox),
    "bbox": bbox,
    "properties": {
        "datetime": None,
        "start_datetime": "2025-01-15T00:00:00Z",
        "end_datetime": "2025-01-01T00:00:00Z",
        "proj:epsg": 4326,
        "eo:bands": [
            {"name": "sst", "description": "Sea Surface Temperature"}
        ],
        "platform": "Multi-satellite",
        "instruments": ["avhrr", "amsr2", "viirs"]
    },
    "links": [],
    "assets": {
        "data": {
            "href": "/app/rasters/global_sst.tif",
            "type": "image/tiff; application=geotiff",
            "roles": ["data"]
        }
    }
})
ds = None

# ── 2. landsat_california — ERROR: bbox in UTM meters ─────────────────────
ds = gdal.Open(os.path.join(RASTER_DIR, 'landsat_california.tif'))
native = get_native_extent(ds)
write_item('landsat_california', {
    "type": "Feature",
    "stac_version": "1.0.0",
    "stac_extensions": [
        "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
        "https://stac-extensions.github.io/eo/v1.1.0/schema.json"
    ],
    "id": "landsat_california",
    "geometry": geojson_polygon(native),
    "bbox": native,
    "properties": {
        "datetime": "2025-03-01T18:30:00Z",
        "proj:epsg": 32611,
        "eo:bands": [
            {"name": "B2", "common_name": "blue"},
            {"name": "B3", "common_name": "green"},
            {"name": "B4", "common_name": "red"},
            {"name": "B5", "common_name": "nir08"},
            {"name": "B6", "common_name": "swir16"},
            {"name": "B7", "common_name": "swir22"}
        ],
        "platform": "Landsat-8",
        "instruments": ["oli", "tirs"]
    },
    "links": [],
    "assets": {
        "data": {
            "href": "/app/rasters/landsat_california.tif",
            "type": "image/tiff; application=geotiff",
            "roles": ["data"]
        }
    }
})
ds = None

# ── 3. greenland_ice — ERROR: bbox longitude signs inverted ────────────────
ds = gdal.Open(os.path.join(RASTER_DIR, 'greenland_ice.tif'))
correct_bbox = compute_wgs84_bbox(ds)
wrong_west = -correct_bbox[0]
wrong_east = -correct_bbox[2]
if wrong_west > wrong_east:
    wrong_west, wrong_east = wrong_east, wrong_west
wrong_bbox = [round(wrong_west, 6), correct_bbox[1],
              round(wrong_east, 6), correct_bbox[3]]
write_item('greenland_ice', {
    "type": "Feature",
    "stac_version": "1.0.0",
    "stac_extensions": [
        "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
        "https://stac-extensions.github.io/eo/v1.1.0/schema.json"
    ],
    "id": "greenland_ice",
    "geometry": geojson_polygon(wrong_bbox),
    "bbox": wrong_bbox,
    "properties": {
        "datetime": "2025-02-15T10:00:00Z",
        "proj:epsg": 3413,
        "eo:bands": [
            {"name": "ice_thickness", "description": "Ice sheet thickness"}
        ],
        "platform": "CryoSat-2",
        "instruments": ["siral"]
    },
    "links": [],
    "assets": {
        "data": {
            "href": "/app/rasters/greenland_ice.tif",
            "type": "image/tiff; application=geotiff",
            "roles": ["data"]
        }
    }
})
ds = None

# ── 4. modis_sinusoidal — ERROR: bbox in sinusoidal meters ────────────────
ds = gdal.Open(os.path.join(RASTER_DIR, 'modis_sinusoidal.tif'))
native = get_native_extent(ds)
sinu_wkt = ds.GetProjection()
write_item('modis_sinusoidal', {
    "type": "Feature",
    "stac_version": "1.0.0",
    "stac_extensions": [
        "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
        "https://stac-extensions.github.io/eo/v1.1.0/schema.json"
    ],
    "id": "modis_sinusoidal",
    "geometry": geojson_polygon(native),
    "bbox": native,
    "properties": {
        "datetime": "2025-04-20T03:15:00Z",
        "proj:epsg": None,
        "proj:wkt2": sinu_wkt,
        "eo:bands": [
            {"name": "sur_refl_b01", "common_name": "red",
             "description": "Surface Reflectance Band 1"},
            {"name": "sur_refl_b02", "common_name": "nir08",
             "description": "Surface Reflectance Band 2"}
        ],
        "platform": "Terra",
        "instruments": ["modis"]
    },
    "links": [],
    "assets": {
        "data": {
            "href": "/app/rasters/modis_sinusoidal.tif",
            "type": "image/tiff; application=geotiff",
            "roles": ["data"]
        }
    }
})
ds = None

# ── 5. sentinel1_sar — ERRORS: wrong proj:epsg AND bbox from wrong zone ───
ds = gdal.Open(os.path.join(RASTER_DIR, 'sentinel1_sar.tif'))
wrong_bbox = compute_bbox_wrong_crs(ds, 32632)
write_item('sentinel1_sar', {
    "type": "Feature",
    "stac_version": "1.0.0",
    "stac_extensions": [
        "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
        "https://stac-extensions.github.io/eo/v1.1.0/schema.json"
    ],
    "id": "sentinel1_sar",
    "geometry": geojson_polygon(wrong_bbox),
    "bbox": wrong_bbox,
    "properties": {
        "datetime": "2025-05-10T06:45:00Z",
        "proj:epsg": 32632,
        "eo:bands": [
            {"name": "VV", "description": "Vertical-Vertical polarization"},
            {"name": "VH", "description": "Vertical-Horizontal polarization"}
        ],
        "platform": "Sentinel-1A",
        "instruments": ["c-sar"]
    },
    "links": [],
    "assets": {
        "data": {
            "href": "/app/rasters/sentinel1_sar.tif",
            "type": "image/tiff; application=geotiff",
            "roles": ["data"]
        }
    }
})
ds = None

# ── 6. antarctic_ice — ERROR: eo:bands lists 3 bands, file has 2 ──────────
ds = gdal.Open(os.path.join(RASTER_DIR, 'antarctic_ice.tif'))
bbox = compute_wgs84_bbox(ds)
write_item('antarctic_ice', {
    "type": "Feature",
    "stac_version": "1.0.0",
    "stac_extensions": [
        "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
        "https://stac-extensions.github.io/eo/v1.1.0/schema.json"
    ],
    "id": "antarctic_ice",
    "geometry": geojson_polygon(bbox),
    "bbox": bbox,
    "properties": {
        "datetime": None,
        "start_datetime": "2025-01-01T00:00:00Z",
        "end_datetime": "2025-06-30T00:00:00Z",
        "proj:epsg": 3031,
        "eo:bands": [
            {"name": "ice_surface_elevation",
             "description": "Ice surface elevation"},
            {"name": "ice_thickness",
             "description": "Ice sheet thickness"},
            {"name": "bedrock_elevation",
             "description": "Bedrock topography"}
        ],
        "platform": "ICESat-2",
        "instruments": ["atlas"]
    },
    "links": [],
    "assets": {
        "data": {
            "href": "/app/rasters/antarctic_ice.tif",
            "type": "image/tiff; application=geotiff",
            "roles": ["data"]
        }
    }
})
ds = None

print("All STAC items generated.")
