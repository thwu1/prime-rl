#!/bin/bash

# Install test-only dependencies
pip3 install pytest==8.3.4 numpy==2.1.3 netCDF4==1.7.2 -q

# Run the cmorizer if it exists
if [ -f /app/cmorize.py ]; then
    python3 /app/cmorize.py
fi

# Run tests and capture exit code
EXIT_CODE=0
python3 -m pytest /tests/test_state.py -v || EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
