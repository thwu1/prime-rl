#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

cd /app

# Run the reconciler if it hasn't been run yet
if [ ! -f /app/anomaly_report.json ]; then
    echo "anomaly_report.json not found, attempting to run reconciler..."
    if [ -f /app/reconciler.py ]; then
        python3 /app/reconciler.py
    fi
fi

# Run tests
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
