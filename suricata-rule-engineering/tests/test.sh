#!/bin/bash

# Install test dependencies

# Run pytest against the verification tests
RESULT=0
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1 || RESULT=$?

# Write reward based on test outcome
mkdir -p /logs/verifier
if [ "$RESULT" -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
