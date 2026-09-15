#!/usr/bin/env bash

set -u

pip3 install pytest==8.3.4 -q

cd /app

# Clean and build the solver with CMake
rm -rf build
cmake -B build 2>&1
CMAKE_RC=$?
if [ $CMAKE_RC -ne 0 ]; then
    echo "CMake configure failed with exit code $CMAKE_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

cmake --build build 2>&1
BUILD_RC=$?
if [ $BUILD_RC -ne 0 ]; then
    echo "Build failed with exit code $BUILD_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the solver
timeout 120 ./build/flood_solver
RUN_RC=$?
if [ $RUN_RC -ne 0 ]; then
    echo "Solver exited with code $RUN_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
pytest /tests/test_state.py -v --tb=short
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RC
