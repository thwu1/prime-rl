#!/bin/bash

# Verify emulator exists
if [ ! -f /app/emulator.py ]; then
    echo "ERROR: /app/emulator.py not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Verify test programs exist
for prog in test_primitives test_shapes test_composite test_triangles test_combined; do
    if [ ! -f "/app/programs/${prog}.hex" ]; then
        echo "ERROR: /app/programs/${prog}.hex not found"
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
        exit 1
    fi
done

cd /app

python3 -m pytest /tests/test_state.py -v --tb=short 2>&1
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
