#!/bin/bash

set +e

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Build the project first
make -C /app clean
make -C /app
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo "Build failed with exit code $BUILD_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
cd /app
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RC
