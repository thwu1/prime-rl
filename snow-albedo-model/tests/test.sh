#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 netCDF4==1.7.2 -q

# Generate forcing data for model validation
python3 /tests/generate_forcing.py
if [ $? -ne 0 ]; then
    echo "Failed to generate forcing data"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Run model with both configurations
mkdir -p /app/output
python3 /app/snow_model.py -m /app/config/fileManager_conDecay.txt 2>&1 || true
python3 /app/snow_model.py -m /app/config/fileManager_varDecay.txt 2>&1 || true

# Generate comparison report if script exists
if [ -f /app/generate_report.py ]; then
    python3 /app/generate_report.py 2>&1 || true
fi

# Run pytest
cd /app
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ "$EXIT_CODE" = "0" ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit 0
