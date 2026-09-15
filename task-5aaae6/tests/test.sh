#!/bin/bash

cd /app

# Create and activate a virtual environment (required by maturin develop)
python3 -m venv .venv
. /app/.venv/bin/activate

# Install test dependencies

# Build the extension module
maturin develop 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "Build failed with exit code $BUILD_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
python3 -m pytest /tests/test_state.py -v 2>&1
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
