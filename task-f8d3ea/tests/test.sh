#!/bin/bash

pip3 install pytest==8.3.4 -q

# Build the packer
cd /app
make clean 2>&1
make 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "Build failed with exit code $BUILD_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the packer
./mseed3pack 2>&1
RUN_EXIT=$?

if [ $RUN_EXIT -ne 0 ]; then
    echo "Program execution failed with exit code $RUN_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Verify output
pytest /tests/test_state.py -v 2>&1
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
