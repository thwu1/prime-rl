#!/usr/bin/env python3
"""Fire behavior simulator - stub implementation.

Requires:
  - GDAL Python bindings (from osgeo import gdal) for raster I/O
  - sqlite3 for fuel parameter database queries
"""
import json
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: firesim.py <config.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        cfg = json.load(f)

    landscape_dir = cfg["landscape_dir"]
    fuel_db = cfg["fuel_db"]
    output_dir = cfg["output_dir"]

    # TODO: Read landscape rasters from landscape_dir using GDAL
    #   - fuel_model.asc, slope.asc, aspect.asc (ESRI ASCII Grid)
    #   - Extract geotransform and CRS from .prj sidecars

    # TODO: Query fuel model parameters from SQLite database at fuel_db
    #   - Table: fuel_models (fm_num, fm_code, is_dynamic, depth_ft, ...)

    # TODO: Implement surface fire behavior calculations
    #   - Rothermel model with all intermediate computations

    # TODO: Implement directional spread (wind + slope vector interaction)

    # TODO: Implement fire growth propagation from ignitions (Dijkstra)

    # TODO: Write output GeoTIFF rasters to output_dir using GDAL
    #   - Float32, preserve geotransform and CRS, nodata = -9999

    # TODO: Write summary.json to output_dir

    print("Stub implementation - not yet complete", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
