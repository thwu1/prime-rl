#!/usr/bin/env python3

"""
Solve the European Multi-Datum Survey Harmonization task.

Transforms 10 survey points from 5 European CRS to ETRS89 geographic (EPSG:4258),
constructs explicit PROJ pipeline strings, determines Helmert parameters,
computes geodesic distances and polygon area, and finds optimal UTM zone.
"""

import csv
import json
from pyproj import Transformer, Geod


def read_survey_data(path="/app/survey_data.csv"):
    points = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            points[row["point_id"]] = {
                "epsg": int(row["epsg"]),
                "easting": float(row["easting"]),
                "northing": float(row["northing"]),
            }
    return points


def build_pipelines():
    """
    Construct explicit PROJ pipeline strings for each CRS to ETRS89 geographic.

    For cross-datum CRS (27700, 28992, 31467): inverse projection -> cartesian ->
    Helmert 7-param -> inverse cartesian on GRS80 -> radians to degrees.

    For same-datum CRS (2154, 25833): inverse projection -> radians to degrees.
    """
    return {
        # OSGB36 / British National Grid -> ETRS89
        # Projection: Transverse Mercator on Airy 1830
        # Datum: OSGB36 to WGS84/ETRS89 via Helmert (EPSG:1314, Position Vector)
        "27700_to_4258": (
            "+proj=pipeline "
            "+step +inv +proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 "
            "+x_0=400000 +y_0=-100000 +ellps=airy "
            "+step +proj=cart +ellps=airy "
            "+step +proj=helmert +x=446.448 +y=-125.157 +z=542.06 "
            "+rx=0.1502 +ry=0.247 +rz=0.8421 +s=-20.4894 "
            "+convention=position_vector "
            "+step +inv +proj=cart +ellps=GRS80 "
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
        ),
        # Amersfoort / RD New -> ETRS89
        # Projection: Oblique Stereographic (Double) on Bessel 1841
        # Datum: Amersfoort to WGS84/ETRS89 via Helmert (EPSG:1751, Coordinate Frame)
        "28992_to_4258": (
            "+proj=pipeline "
            "+step +inv +proj=sterea +lat_0=52.15616055555556 "
            "+lon_0=5.38763888888889 +k=0.9999079 "
            "+x_0=155000 +y_0=463000 +ellps=bessel "
            "+step +proj=cart +ellps=bessel "
            "+step +proj=helmert +x=565.417 +y=50.3319 +z=465.552 "
            "+rx=-0.398957 +ry=0.343988 +rz=-1.8774 +s=4.0725 "
            "+convention=coordinate_frame "
            "+step +inv +proj=cart +ellps=GRS80 "
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
        ),
        # DHDN / 3-degree Gauss-Kruger zone 3 -> ETRS89
        # Projection: Transverse Mercator on Bessel 1841
        # Central meridian: 9 deg, false easting: 3500000 (zone prefix 3 + 500000)
        # Datum: DHDN to WGS84/ETRS89 via Helmert (EPSG:1777, Position Vector)
        "31467_to_4258": (
            "+proj=pipeline "
            "+step +inv +proj=tmerc +lat_0=0 +lon_0=9 +k=1 "
            "+x_0=3500000 +y_0=0 +ellps=bessel "
            "+step +proj=cart +ellps=bessel "
            "+step +proj=helmert +x=598.1 +y=73.7 +z=418.2 "
            "+rx=0.202 +ry=0.045 +rz=-2.455 +s=6.7 "
            "+convention=position_vector "
            "+step +inv +proj=cart +ellps=GRS80 "
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
        ),
        # RGF93 v1 / Lambert-93 -> ETRS89
        # Projection: Lambert Conformal Conic (2SP) on GRS80
        # Datum: RGF93 is a realization of ETRS89 (no datum transform needed)
        "2154_to_4258": (
            "+proj=pipeline "
            "+step +inv +proj=lcc +lat_0=46.5 +lon_0=3 "
            "+lat_1=49 +lat_2=44 +x_0=700000 +y_0=6600000 +ellps=GRS80 "
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
        ),
        # ETRS89 / UTM zone 33N -> ETRS89
        # Projection: UTM zone 33 on GRS80
        # Datum: already ETRS89 (no datum transform needed)
        "25833_to_4258": (
            "+proj=pipeline "
            "+step +inv +proj=utm +zone=33 +ellps=GRS80 "
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
        ),
    }


def get_helmert_parameters():
    """
    Return the Helmert 7-parameter sets used for each datum transformation.
    """
    return {
        "27700": {
            "x": 446.448,
            "y": -125.157,
            "z": 542.06,
            "rx": 0.1502,
            "ry": 0.247,
            "rz": 0.8421,
            "s": -20.4894,
            "convention": "position_vector",
        },
        "28992": {
            "x": 565.417,
            "y": 50.3319,
            "z": 465.552,
            "rx": -0.398957,
            "ry": 0.343988,
            "rz": -1.8774,
            "s": 4.0725,
            "convention": "coordinate_frame",
        },
        "31467": {
            "x": 598.1,
            "y": 73.7,
            "z": 418.2,
            "rx": 0.202,
            "ry": 0.045,
            "rz": -2.455,
            "s": 6.7,
            "convention": "position_vector",
        },
    }


def transform_points(points, pipelines):
    """Transform all points to ETRS89 geographic using the constructed pipelines."""
    etrs89_coords = {}
    for pid, pdata in sorted(points.items()):
        epsg = pdata["epsg"]
        pipeline_key = f"{epsg}_to_4258"
        pipeline = pipelines[pipeline_key]

        transformer = Transformer.from_pipeline(pipeline)
        lon, lat = transformer.transform(pdata["easting"], pdata["northing"])
        etrs89_coords[pid] = [round(lon, 8), round(lat, 8)]

    return etrs89_coords


def compute_geodesic_distances(etrs89_coords, pairs):
    """Compute geodesic distances on GRS80 between specified point pairs."""
    geod = Geod(ellps="GRS80")
    distances = {}
    for pair in pairs:
        p1, p2 = pair.split("_")
        lon1, lat1 = etrs89_coords[p1]
        lon2, lat2 = etrs89_coords[p2]
        _, _, dist = geod.inv(lon1, lat1, lon2, lat2)
        distances[pair] = round(abs(dist), 2)
    return distances


def compute_polygon_area(etrs89_coords, vertices):
    """Compute geodesic polygon area on GRS80."""
    geod = Geod(ellps="GRS80")
    lons = [etrs89_coords[p][0] for p in vertices]
    lats = [etrs89_coords[p][1] for p in vertices]
    area, _ = geod.polygon_area_perimeter(lons, lats)
    return round(abs(area), 2)


def compute_optimal_utm_zone(etrs89_coords):
    """Determine the UTM zone whose central meridian is closest to mean longitude."""
    avg_lon = sum(c[0] for c in etrs89_coords.values()) / len(etrs89_coords)
    return int((avg_lon + 180) / 6) + 1


def main():
    points = read_survey_data()
    pipelines = build_pipelines()
    helmert_params = get_helmert_parameters()
    etrs89_coords = transform_points(points, pipelines)

    # Polygon edges in convex-hull order: London, Amsterdam, Hamburg, Italy, Paris
    distance_pairs = ["P01_P03", "P03_P05", "P05_P09", "P09_P07", "P07_P01"]
    polygon_vertices = ["P01", "P03", "P05", "P09", "P07"]

    geodesic_distances = compute_geodesic_distances(etrs89_coords, distance_pairs)
    polygon_area = compute_polygon_area(etrs89_coords, polygon_vertices)
    optimal_utm = compute_optimal_utm_zone(etrs89_coords)

    results = {
        "pipelines": pipelines,
        "etrs89_coordinates": etrs89_coords,
        "helmert_parameters": helmert_params,
        "geodesic_distances": geodesic_distances,
        "polygon_area_m2": polygon_area,
        "optimal_utm_zone": optimal_utm,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results written to /app/results.json")
    print(f"Transformed {len(etrs89_coords)} points to ETRS89")
    print(f"Computed {len(geodesic_distances)} geodesic distances")
    print(f"Polygon area: {polygon_area:.0f} m^2")
    print(f"Optimal UTM zone: {optimal_utm}")


if __name__ == "__main__":
    main()
