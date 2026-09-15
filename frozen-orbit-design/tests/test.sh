#!/bin/bash

# Validate output format with jq filter first
if [ -f /app/results.json ]; then
    jq -e -f /app/validate_output.jq /app/results.json > /dev/null 2>&1
    JQ_EXIT=$?
    if [ $JQ_EXIT -ne 0 ]; then
        echo "FAIL: jq validation filter rejected /app/results.json"
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
        exit 1
    fi
fi

python3 -m pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
