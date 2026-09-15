#!/bin/bash

# Install test dependencies
python3 -m pip install pytest==8.3.4 -q 2>&1

# Ensure the task file is accessible
if [ ! -f /app/bf16_arith.py ] && [ -f /opt/task/bf16_arith.py ]; then
    cp /opt/task/bf16_arith.py /app/bf16_arith.py
fi

# Run pytest
cd /app
python3 -m pytest /tests/test_state.py -v
PYTEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
