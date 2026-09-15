#!/usr/bin/env python3
"""Create corrupted geospatial catalog GeoPackage for the repair task."""

import math
import os
from osgeo import ogr, osr

R = 6378137.0  # WGS84 semi-major axis


def lon_to_3857(lon):
    return lon * math.pi / 180.0 * R


def lat_to_3857(lat):
    return R * math.log(math.tan(math.pi / 4.0 + lat * math.pi / 360.0))


def make_bbox(w, s, e, n):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(w, s)
    ring.AddPoint(e, s)
    ring.AddPoint(e, n)
    ring.AddPoint(w, n)
    ring.AddPoint(w, s)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def make_bowtie(w, s, e, n):
    """Create a self-intersecting bowtie polygon from bbox coords."""
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(w, s)
    ring.AddPoint(e, n)
    ring.AddPoint(e, s)
    ring.AddPoint(w, n)
    ring.AddPoint(w, s)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def make_3857_bbox(w, s, e, n):
    """Create bbox polygon using EPSG:3857 coordinates (stored as if EPSG:4326)."""
    mx_w = lon_to_3857(w)
    my_s = lat_to_3857(s)
    mx_e = lon_to_3857(e)
    my_n = lat_to_3857(n)
    return make_bbox(mx_w, my_s, mx_e, my_n)


def make_swapped_bbox(w, s, e, n):
    """Create bbox with lat/lon transposed."""
    return make_bbox(s, w, n, e)


RECORDS = [
    # --- Clean records (19) ---
    {"id": "PNW-ELEV-30", "name": "Pacific Northwest Elevation Model 30m",
     "cat": "elevation", "res": 30, "qual": 0.90, "size": 12.0,
     "bands": "elevation,slope", "ts": "2019-01-01", "te": "2020-12-31",
     "geom_fn": lambda: make_bbox(-130, 40, -110, 55)},

    {"id": "WA-ELEV-10", "name": "Washington State Elevation 10m",
     "cat": "elevation", "res": 10, "qual": 0.93, "size": 4.0,
     "bands": "elevation,slope,aspect", "ts": "2021-01-01", "te": "2021-12-31",
     "geom_fn": lambda: make_bbox(-125, 46, -117, 49)},

    {"id": "OR-ELEV-10", "name": "Oregon State Elevation 10m",
     "cat": "elevation", "res": 10, "qual": 0.91, "size": 3.5,
     "bands": "elevation,slope,aspect", "ts": "2021-01-01", "te": "2021-12-31",
     "geom_fn": lambda: make_bbox(-125, 42, -117, 46)},

    {"id": "CASC-ELEV-5", "name": "Cascade Range High-Res Elevation 5m",
     "cat": "elevation", "res": 5, "qual": 0.95, "size": 6.0,
     "bands": "elevation,slope,aspect,curvature", "ts": "2022-01-01", "te": "2022-12-31",
     "geom_fn": lambda: make_bbox(-123, 44, -120, 48)},

    {"id": "BC-ELEV-10", "name": "British Columbia Elevation 10m",
     "cat": "elevation", "res": 10, "qual": 0.88, "size": 5.0,
     "bands": "elevation", "ts": "2020-01-01", "te": "2020-12-31",
     "geom_fn": lambda: make_bbox(-130, 48, -115, 55)},

    {"id": "PNW-LC-10", "name": "PNW Land Cover 10m",
     "cat": "landcover", "res": 10, "qual": 0.86, "size": 25.0,
     "bands": "landcover,confidence", "ts": "2020-01-01", "te": "2020-12-31",
     "geom_fn": lambda: make_bbox(-130, 40, -110, 55)},

    {"id": "WA-FOREST-20", "name": "Washington Forest Cover 20m",
     "cat": "landcover", "res": 20, "qual": 0.89, "size": 2.0,
     "bands": "forest_cover,canopy_height,landcover", "ts": "2019-01-01", "te": "2022-12-31",
     "geom_fn": lambda: make_bbox(-124, 46, -117, 49)},

    {"id": "OR-FOREST-20", "name": "Oregon Forest Cover 20m",
     "cat": "landcover", "res": 20, "qual": 0.87, "size": 1.8,
     "bands": "forest_cover,canopy_height,landcover", "ts": "2019-01-01", "te": "2022-12-31",
     "geom_fn": lambda: make_bbox(-124, 42, -117, 46)},

    {"id": "BC-FOREST-20", "name": "BC Forest Cover 20m",
     "cat": "landcover", "res": 20, "qual": 0.84, "size": 3.0,
     "bands": "forest_cover,landcover", "ts": "2020-01-01", "te": "2021-12-31",
     "geom_fn": lambda: make_bbox(-130, 48, -118, 54)},

    {"id": "PNW-VEG-30", "name": "PNW Vegetation Index 30m",
     "cat": "vegetation", "res": 30, "qual": 0.88, "size": 5.0,
     "bands": "ndvi,evi,lai", "ts": "2020-01-01", "te": "2022-12-31",
     "geom_fn": lambda: make_bbox(-128, 42, -115, 52)},

    {"id": "PNW-PRECIP-1000", "name": "PNW Precipitation 1km",
     "cat": "climate", "res": 1000, "qual": 0.85, "size": 0.5,
     "bands": "precipitation,snowfall", "ts": "2015-01-01", "te": "2023-12-31",
     "geom_fn": lambda: make_bbox(-135, 38, -105, 56)},

    {"id": "PNW-TEMP-1000", "name": "PNW Temperature 1km",
     "cat": "climate", "res": 1000, "qual": 0.87, "size": 0.4,
     "bands": "temperature,humidity", "ts": "2015-01-01", "te": "2023-12-31",
     "geom_fn": lambda: make_bbox(-135, 38, -105, 56)},

    {"id": "WA-CLIMATE-500", "name": "Washington Climate Data 500m",
     "cat": "climate", "res": 500, "qual": 0.90, "size": 0.8,
     "bands": "temperature,precipitation,wind", "ts": "2018-01-01", "te": "2023-12-31",
     "geom_fn": lambda: make_bbox(-125, 46, -117, 49)},

    {"id": "WUSA-TEMP-1000", "name": "Western US Temperature 1km",
     "cat": "climate", "res": 1000, "qual": 0.84, "size": 0.6,
     "bands": "temperature,max_temp,min_temp", "ts": "2016-01-01", "te": "2023-12-31",
     "geom_fn": lambda: make_bbox(-130, 30, -105, 45)},

    {"id": "PNW-SOIL-250", "name": "PNW Soil Properties 250m",
     "cat": "soil", "res": 250, "qual": 0.80, "size": 2.0,
     "bands": "soil_type,organic_carbon,ph", "ts": "2019-01-01", "te": "2019-12-31",
     "geom_fn": lambda: make_bbox(-130, 40, -110, 55)},

    {"id": "PNW-WATER-30", "name": "PNW Water Bodies 30m",
     "cat": "hydrology", "res": 30, "qual": 0.91, "size": 3.0,
     "bands": "water_mask,water_type", "ts": "2020-01-01", "te": "2020-12-31",
     "geom_fn": lambda: make_bbox(-130, 40, -110, 55)},

    {"id": "PNW-SNOW-100", "name": "PNW Snow Cover 100m",
     "cat": "hydrology", "res": 100, "qual": 0.83, "size": 1.5,
     "bands": "snow_cover,snow_depth", "ts": "2019-01-01", "te": "2022-12-31",
     "geom_fn": lambda: make_bbox(-130, 42, -115, 52)},

    {"id": "CASC-GLACIER-5", "name": "Cascades Glacier Monitor 5m",
     "cat": "hydrology", "res": 5, "qual": 0.94, "size": 0.5,
     "bands": "glacier_extent,ice_thickness", "ts": "2021-01-01", "te": "2022-12-31",
     "geom_fn": lambda: make_bbox(-122, 46, -121, 48)},

    {"id": "PNW-FIRE-20", "name": "PNW Fire Risk 20m",
     "cat": "hazard", "res": 20, "qual": 0.84, "size": 4.0,
     "bands": "fire_risk,burn_severity,fuel_load", "ts": "2019-01-01", "te": "2023-12-31",
     "geom_fn": lambda: make_bbox(-128, 40, -112, 52)},

    # --- Corrupted records: CRS mismatch (3) ---
    # Coordinates are EPSG:3857 (Web Mercator meters) stored as if EPSG:4326 (degrees)
    {"id": "MODIS-LST-1000", "name": "MODIS Land Surface Temperature 1km",
     "cat": "climate", "res": 1000, "qual": 0.82, "size": 0.8,
     "bands": "lst,emissivity", "ts": "2018-01-01", "te": "2023-12-31",
     "geom_fn": lambda: make_3857_bbox(-130, 40, -110, 55)},

    {"id": "SENTINEL-NDVI-10", "name": "Sentinel-2 NDVI Composite 10m",
     "cat": "vegetation", "res": 10, "qual": 0.91, "size": 3.5,
     "bands": "ndvi,evi,red_edge", "ts": "2019-06-01", "te": "2022-11-30",
     "geom_fn": lambda: make_3857_bbox(-125, 46, -117, 49)},

    {"id": "LANDSAT-TC-30", "name": "Landsat Tree Cover 30m",
     "cat": "landcover", "res": 30, "qual": 0.85, "size": 4.5,
     "bands": "tree_cover,bare_ground,water", "ts": "2020-01-01", "te": "2021-12-31",
     "geom_fn": lambda: make_3857_bbox(-128, 42, -115, 52)},

    # --- Corrupted records: Coordinate swap (2) ---
    # Latitude and longitude values are transposed
    {"id": "ASTER-DEM-30", "name": "ASTER Global DEM 30m Extract",
     "cat": "elevation", "res": 30, "qual": 0.88, "size": 1.5,
     "bands": "elevation,slope", "ts": "2020-03-01", "te": "2020-09-30",
     "geom_fn": lambda: make_swapped_bbox(-122.5, 46, -120.5, 48)},

    {"id": "SRTM-FILL-90", "name": "SRTM Void-Filled DEM 90m",
     "cat": "elevation", "res": 90, "qual": 0.79, "size": 0.3,
     "bands": "elevation,void_mask", "ts": "2000-02-11", "te": "2000-02-22",
     "geom_fn": lambda: make_swapped_bbox(-124, 44, -119, 49)},

    # --- Corrupted records: Invalid geometry (2) ---
    # Self-intersecting bowtie polygon instead of rectangle
    {"id": "NLCD-LC-30", "name": "NLCD Land Cover 30m",
     "cat": "landcover", "res": 30, "qual": 0.86, "size": 8.0,
     "bands": "landcover,impervious,canopy", "ts": "2019-01-01", "te": "2021-12-31",
     "geom_fn": lambda: make_bowtie(-125, 42, -115, 49)},

    {"id": "PRISM-PRECIP-800", "name": "PRISM Climate Normals 800m",
     "cat": "climate", "res": 800, "qual": 0.88, "size": 1.2,
     "bands": "precipitation,tmin,tmax", "ts": "2017-01-01", "te": "2023-12-31",
     "geom_fn": lambda: make_bowtie(-130, 35, -105, 55)},

    # --- Corrupted records: Temporal inversion (2) ---
    # temporal_start and temporal_end are swapped
    {"id": "WA-LIDAR-1", "name": "Washington Lidar Point Cloud DEM 1m",
     "cat": "elevation", "res": 1, "qual": 0.96, "size": 2.0,
     "bands": "elevation,intensity,return_count", "ts": "2023-06-30", "te": "2019-01-01",
     "geom_fn": lambda: make_bbox(-122, 47, -121, 48)},

    {"id": "GRIDMET-CLIMATE-4000", "name": "gridMET Meteorological Data 4km",
     "cat": "climate", "res": 4000, "qual": 0.83, "size": 0.2,
     "bands": "temperature,precipitation,wind_speed,humidity",
     "ts": "2023-12-31", "te": "2018-01-01",
     "geom_fn": lambda: make_bbox(-130, 25, -100, 50)},
]


def main():
    output_path = '/app/catalog.gpkg'
    if os.path.exists(output_path):
        os.remove(output_path)

    driver = ogr.GetDriverByName('GPKG')
    ds = driver.CreateDataSource(output_path)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    layer = ds.CreateLayer('datasets', srs, ogr.wkbPolygon)

    layer.CreateField(ogr.FieldDefn('dataset_id', ogr.OFTString))
    layer.CreateField(ogr.FieldDefn('name', ogr.OFTString))
    layer.CreateField(ogr.FieldDefn('category', ogr.OFTString))
    layer.CreateField(ogr.FieldDefn('resolution_m', ogr.OFTInteger))
    fld = ogr.FieldDefn('quality_score', ogr.OFTReal)
    fld.SetWidth(10)
    fld.SetPrecision(2)
    layer.CreateField(fld)
    fld = ogr.FieldDefn('size_gb', ogr.OFTReal)
    fld.SetWidth(10)
    fld.SetPrecision(1)
    layer.CreateField(fld)
    layer.CreateField(ogr.FieldDefn('bands', ogr.OFTString))
    layer.CreateField(ogr.FieldDefn('temporal_start', ogr.OFTString))
    layer.CreateField(ogr.FieldDefn('temporal_end', ogr.OFTString))

    for rec in RECORDS:
        feat = ogr.Feature(layer.GetLayerDefn())
        feat.SetField('dataset_id', rec['id'])
        feat.SetField('name', rec['name'])
        feat.SetField('category', rec['cat'])
        feat.SetField('resolution_m', rec['res'])
        feat.SetField('quality_score', rec['qual'])
        feat.SetField('size_gb', rec['size'])
        feat.SetField('bands', rec['bands'])
        feat.SetField('temporal_start', rec['ts'])
        feat.SetField('temporal_end', rec['te'])
        feat.SetGeometry(rec['geom_fn']())
        layer.CreateFeature(feat)
        feat = None

    ds = None
    print(f"Created {output_path} with {len(RECORDS)} records")


if __name__ == '__main__':
    main()
