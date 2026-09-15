#!/bin/bash
set -e

# Ensure dependencies are available
pip3 install rasterio==1.3.10 shapely==2.0.4 pyproj==3.6.1 numpy==1.26.4 -q 2>/dev/null || true

cp /solution/solve_pipeline.py /app/pipeline.py
cd /app
python3 /app/pipeline.py
