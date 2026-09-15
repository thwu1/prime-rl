#!/bin/bash

set -e

# Ensure setuptools is available (for pip download fallback)
pip3 install setuptools==75.6.0 -q 2>/dev/null || true

# Generate the correct gsw_pipeline.c from official GSW-C source
python3 /solution/build_pipeline.py

# Apply the corrected pipeline to /app
cp /tmp/gsw_pipeline_correct.c /app/gsw_pipeline.c

# Build and run
cd /app
make clean
make
./ctd_pipeline

echo "Solution applied successfully."
