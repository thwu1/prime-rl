#!/bin/bash

pip3 install pytest==8.3.4 numpy==1.26.4 xarray==2024.6.0 zarr==2.17.2 numcodecs==0.12.1 pandas==2.2.2 cftime==1.6.4 packaging==24.1 -q

# Ensure raw data exists (fallback if Docker build data was lost)
if [ ! -f /data/raw_data/MODEL-A/metadata.json ]; then
    echo "Raw data not found, regenerating..."
    python3 /tests/generate_data.py
fi

cd /app
RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?
echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
