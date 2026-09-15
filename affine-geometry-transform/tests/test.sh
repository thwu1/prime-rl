#!/bin/bash

set -u

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Install Node.js project dependencies
cd /app && npm install --ignore-scripts 2>/dev/null

# Run pytest
RESULT=0
pytest /tests/test_state.py -v --tb=short || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ "$RESULT" -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
