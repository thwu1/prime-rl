#!/usr/bin/env bash

set -e

cd /app

# Inspect the GeoPackage to understand its structure
ogrinfo -so /app/data/hydrofabric.gpkg catchments
ogrinfo -so /app/data/hydrofabric.gpkg nexuses

# Run the analysis
cp /solution/analyze.py /app/analyze.py
python3 /app/analyze.py
