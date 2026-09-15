#!/bin/bash

pip3 install pytest==8.3.3 numpy==1.26.4 scipy==1.13.1 matplotlib==3.9.2 -q

# Generate synthetic data (deterministic, idempotent)
if [ -f /opt/generate_data.py ]; then
    python3 /opt/generate_data.py
elif [ -f /app/generate_data.py ]; then
    python3 /app/generate_data.py
else
    echo "ERROR: generate_data.py not found" >&2
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
cd /app
pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
