#!/bin/bash

set -u

pip3 install pytest==8.3.4 -q 2>/dev/null

# Ensure the redact package directory exists
mkdir -p /app/redact

# Copy the Go test file into the package directory
cp /tests/redact_test.go /app/redact/redact_test.go

cd /app

# Ensure dependencies are resolved
go mod tidy 2>&1

# Run pytest verification
PYTEST_EXIT=0
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1 || PYTEST_EXIT=$?

if [ "$PYTEST_EXIT" -eq 0 ]; then
    mkdir -p /logs/verifier
    echo "1.0" > /logs/verifier/reward.txt
    echo "ALL TESTS PASSED"
    exit 0
else
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    echo "TESTS FAILED (pytest=$PYTEST_EXIT)"
    exit 1
fi
