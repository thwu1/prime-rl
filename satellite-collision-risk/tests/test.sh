#!/bin/bash

pip3 install pytest==8.3.4 -q

# Build the Maven project
cd /app
mvn package -q 2>&1
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo "Maven build failed with exit code $BUILD_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run verification tests
cd /
pytest /tests/test_state.py -v 2>&1
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_RC
