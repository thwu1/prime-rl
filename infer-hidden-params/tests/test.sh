#!/usr/bin/env bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q 2>/dev/null || pip3 install pytest==8.3.4 -q 2>/dev/null

# Generate test replays into the SQLite database
python3 /tests/generate_test_data.py

# Run agent's inference
if [ -f /app/infer_params.py ]; then
    python3 /app/infer_params.py
else
    echo "ERROR: /app/infer_params.py not found"
fi

# Run verification (checks both JSON and SQLite results)
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
