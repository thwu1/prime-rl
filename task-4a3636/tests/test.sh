#!/bin/bash

# Install test dependencies

# Run the candidate's program to generate output
cd /app
if [ -f /app/nfiq2_features.py ]; then
    python3 /app/nfiq2_features.py 2>/dev/null
fi

# Run tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
