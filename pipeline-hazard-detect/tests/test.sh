#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Build the testbench first
make maxicore32_tb 2>&1
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo "Build failed with exit code $BUILD_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
pytest /tests/test_state.py -v 2>&1
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
