#!/usr/bin/env bash

set -u

pip3 install pytest==8.3.4 -q

# Compile and run the CDS pricer via pipeline
cd /app
bash pipeline.sh 2>/tmp/build_err.txt
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo "Pipeline failed:"
    cat /tmp/build_err.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

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
