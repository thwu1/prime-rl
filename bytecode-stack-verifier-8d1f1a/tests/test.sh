#!/bin/bash

set -u

# Build all tools
make -C /app/src clean
make -C /app/src
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Verify all binaries exist
for bin in verifier optimizer bcdump; do
    if [ ! -x "/app/src/$bin" ]; then
        echo "$bin binary not found"
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
        exit 1
    fi
done

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run tests
pytest /tests/test_state.py -v
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RC
