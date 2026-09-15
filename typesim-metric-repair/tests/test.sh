#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 scipy==1.13.1 numpy==1.26.4 -q

# Restore task data from backup if /app was cleared
if [ ! -f /app/test_cases.json ] && [ -d /opt/task_setup ]; then
    mkdir -p /app/typesim
    cp -r /opt/task_setup/* /app/
fi

# Run tests
export PYTHONPATH=/app:$PYTHONPATH
RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

echo "$RESULT"

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
