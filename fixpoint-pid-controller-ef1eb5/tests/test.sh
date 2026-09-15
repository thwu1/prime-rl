#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Build the simulation
cd /app
make clean 2>/dev/null || true
make 2>&1
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the simulation to produce trace
./sim_harness 2>&1
RUN_RC=$?

if [ $RUN_RC -ne 0 ]; then
    echo "Simulation run failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
cd /tests
python3 -m pytest test_state.py -v 2>&1
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RC
