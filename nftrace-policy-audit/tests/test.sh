#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 pyyaml==6.0.2 -q

# Check that the audit script exists
if [ ! -f /app/audit.py ]; then
    echo "ERROR: /app/audit.py not found"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

cd /app
python3 /app/audit.py
ANALYZER_EXIT=$?

if [ $ANALYZER_EXIT -ne 0 ]; then
    echo "ERROR: audit.py exited with code $ANALYZER_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
pytest /tests/test_state.py -v
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
