#!/usr/bin/env bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run pytest tests
cd /app
RESULT=$(python3 -m pytest /tests/test_state.py -v 2>&1) || true
echo "$RESULT"

# Write reward based on pytest outcome
mkdir -p /logs/verifier
if echo "$RESULT" | grep -q "failed\|error\|ERROR"; then
    echo "0.0" > /logs/verifier/reward.txt
elif echo "$RESULT" | grep -q "passed"; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
