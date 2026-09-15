#!/bin/bash

pip3 install pytest==8.3.4 -q

# Try to run the pipeline if output doesn't exist yet
if [ ! -f /app/output/results.json ]; then
    cd /app
    for script in evaluate.py pipeline.py main.py; do
        if [ -f "/app/$script" ]; then
            python3 "/app/$script" 2>&1 || true
            [ -f /app/output/results.json ] && break
        fi
    done
fi

# Run pytest and capture exit code
pytest /tests/test_state.py -v 2>&1
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
