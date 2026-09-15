#!/usr/bin/env python3
"""Generate synthetic geospatial data and configuration for multi-criteria site suitability analysis."""
import json
import os

from osgeo import ogr, osr


def create_srs(epsg):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    return srs


def add_polygon(layer, coords, fields=None):
    feat = ogr.Feature(layer.GetLayerDefn())
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in coords:
        ring.AddPoint(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    feat.SetGeometry(poly)
    if fields:
        for k, v in fields.items():
            feat.SetField(k, v)
    layer.CreateFeature(feat)


def add_point(layer, x, y, fields=None):
    feat = ogr.Feature(layer.GetLayerDefn())
    pt = ogr.Geometry(ogr.wkbPoint)
    pt.AddPoint(x, y)
    feat.SetGeometry(pt)
    if fields:
        for k, v in fields.items():
            feat.SetField(k, v)
    layer.CreateFeature(feat)


def add_line(layer, coords, fields=None):
    feat = ogr.Feature(layer.GetLayerDefn())
    line = ogr.Geometry(ogr.wkbLineString)
    for x, y in coords:
        line.AddPoint(x, y)
    feat.SetGeometry(line)
    if fields:
        for k, v in fields.items():
            feat.SetField(k, v)
    layer.CreateFeature(feat)


def create_criteria_json(path):
    """Write the analysis configuration file."""
    config = {
        "analysis": {
            "crs": "EPSG:32636",
            "resolution_m": 50,
            "extent_layer": "boundary"
        },
        "criteria": [
            {
                "name": "hospital_proximity",
                "layer": "hospitals",
                "type": "proximity",
                "weight": 3,
                "description": "New facility should be far from existing hospitals to maximize spatial coverage of services",
                "reclassify_rules": [
                    {"condition": "distance <= 200m", "value": 10, "label": "Too close to existing hospital"},
                    {"condition": "200m < distance <= 500m", "value": 50, "label": "Moderate distance"},
                    {"condition": "distance > 500m", "value": 100, "label": "Good coverage gap"}
                ]
            },
            {
                "name": "road_access",
                "layer": "roads",
                "type": "proximity",
                "weight": 2,
                "description": "Site should be close to road network for accessibility",
                "reclassify_rules": [
                    {"condition": "distance <= 100m", "value": 100, "label": "Excellent access"},
                    {"condition": "100m < distance <= 300m", "value": 50, "label": "Moderate access"},
                    {"condition": "distance > 300m", "value": 10, "label": "Poor access"}
                ]
            },
            {
                "name": "flood_risk",
                "layer": "flood_zones",
                "type": "presence",
                "weight": 5,
                "description": "Site must avoid flood-prone areas",
                "reclassify_rules": [
                    {"condition": "inside flood zone (pixel value >= 1)", "value": 10, "label": "High risk"},
                    {"condition": "outside flood zone (pixel value == 0)", "value": 100, "label": "Safe"}
                ]
            }
        ],
        "formula": "weighted_average = sum(weight_i * reclassified_i) / sum(weight_i)",
        "candidate_analysis": {
            "suitability_threshold": 70,
            "min_contiguous_area_ha": 5.0,
            "connectivity": 4,
            "description": "Identify contiguous regions of pixels scoring strictly above suitability_threshold, filter those meeting min_contiguous_area_ha, compute per-patch statistics"
        },
        "output": {
            "suitability_tif": "/app/output/suitability.tif",
            "candidates_json": "/app/output/candidates.json",
            "results_json": "/app/output/results.json",
            "results_format": {
                "total_suitable_area_ha": "float: total area in hectares of all pixels with suitability strictly > suitability_threshold, rounded to 2 decimal places",
                "num_candidate_patches": "integer: number of contiguous patches meeting minimum area requirement",
                "best_candidate": {
                    "patch_id": "integer: 1-indexed ID of the highest mean_suitability patch",
                    "centroid_x": "float: X coordinate (in analysis CRS) of the geometric centroid of the patch pixel centers, rounded to 1 decimal place",
                    "centroid_y": "float: Y coordinate (in analysis CRS) of the geometric centroid of the patch pixel centers, rounded to 1 decimal place",
                    "area_ha": "float: area of the patch in hectares, rounded to 2 decimal places",
                    "mean_suitability": "float: mean suitability score within the patch, rounded to 2 decimal places"
                },
                "mean_suitability_all": "float: arithmetic mean suitability across ALL valid (non-zero) pixels in the suitability raster, rounded to 2 decimal places"
            },
            "candidates_format": {
                "description": "JSON array of objects, one per qualifying patch, sorted by mean_suitability descending",
                "fields": {
                    "patch_id": "integer: 1-indexed patch identifier assigned after sorting",
                    "centroid_x": "float: X coordinate of geometric centroid of patch pixel centers in analysis CRS, rounded to 1 decimal place",
                    "centroid_y": "float: Y coordinate of geometric centroid of patch pixel centers in analysis CRS, rounded to 1 decimal place",
                    "area_ha": "float: patch area in hectares, rounded to 2 decimal places",
                    "mean_suitability": "float: mean suitability within patch, rounded to 2 decimal places",
                    "max_suitability": "float: maximum suitability pixel value within patch"
                }
            }
        }
    }
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f'Created {path}')


def main():
    os.makedirs('/app', exist_ok=True)

    # --- Create criteria.json ---
    create_criteria_json('/app/criteria.json')

    # --- Create GeoPackage ---
    gpkg_path = '/app/site_data.gpkg'
    if os.path.exists(gpkg_path):
        os.remove(gpkg_path)

    driver = ogr.GetDriverByName('GPKG')
    ds = driver.CreateDataSource(gpkg_path)
    srs = create_srs(32636)

    # --- Boundary layer (4km x 4km rectangle) ---
    lyr = ds.CreateLayer('boundary', srs, ogr.wkbPolygon)
    add_polygon(lyr, [
        (500000, 4000000), (504000, 4000000),
        (504000, 4004000), (500000, 4004000),
        (500000, 4000000)
    ])

    # --- Hospitals layer (6 points) ---
    lyr = ds.CreateLayer('hospitals', srs, ogr.wkbPoint)
    lyr.CreateField(ogr.FieldDefn('name', ogr.OFTString))
    hospitals = [
        (501000, 4001000, 'City General'),
        (503000, 4001000, 'East Wing'),
        (501000, 4003000, 'North Clinic'),
        (503000, 4003000, 'NE Medical'),
        (502000, 4002000, 'Central Hub'),
        (500500, 4002000, 'West Aid'),
    ]
    for x, y, name in hospitals:
        add_point(lyr, x, y, {'name': name})

    # --- Roads layer (6 lines forming a grid) ---
    lyr = ds.CreateLayer('roads', srs, ogr.wkbLineString)
    lyr.CreateField(ogr.FieldDefn('road_type', ogr.OFTString))
    roads = [
        ([(500000, 4001000), (504000, 4001000)], 'primary'),
        ([(500000, 4002000), (504000, 4002000)], 'primary'),
        ([(500000, 4003000), (504000, 4003000)], 'secondary'),
        ([(501000, 4000000), (501000, 4004000)], 'primary'),
        ([(502000, 4000000), (502000, 4004000)], 'secondary'),
        ([(503000, 4000000), (503000, 4004000)], 'primary'),
    ]
    for coords, rtype in roads:
        add_line(lyr, coords, {'road_type': rtype})

    # --- Flood zones layer (2 polygons) ---
    lyr = ds.CreateLayer('flood_zones', srs, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn('risk_level', ogr.OFTString))
    add_polygon(lyr, [
        (500000, 4000000), (501500, 4000000),
        (501500, 4001500), (500000, 4001500),
        (500000, 4000000)
    ], {'risk_level': 'high'})
    add_polygon(lyr, [
        (502500, 4002500), (504000, 4002500),
        (504000, 4004000), (502500, 4004000),
        (502500, 4002500)
    ], {'risk_level': 'moderate'})

    ds = None
    print(f'Created {gpkg_path}')


if __name__ == '__main__':
    main()
