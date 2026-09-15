#!/usr/bin/env bash

# numpy, scipy, netCDF4 are pre-installed via apt in the Docker image.
# No additional pip dependencies needed.

cd /app
python3 /solution/analysis.py
