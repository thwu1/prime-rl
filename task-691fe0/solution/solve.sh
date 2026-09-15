#!/bin/bash

pip3 install numpy==1.26.4 xarray==2024.6.0 zarr==2.17.2 numcodecs==0.12.1 pandas==2.2.2 cftime==1.6.4 packaging==24.1 -q

# Ensure raw data exists (fallback if Docker build data was lost)
if [ ! -f /data/raw_data/MODEL-A/metadata.json ]; then
    echo "Raw data not found, regenerating..."
    python3 /solution/generate_data.py
fi

python3 /solution/pipeline.py
