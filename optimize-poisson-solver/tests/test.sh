#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q

cd /app

# Verify required source files exist
if [ ! -f CMakeLists.txt ]; then
    echo "CMakeLists.txt not found in /app/"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

if [ ! -f fast_poisson.c ]; then
    echo "fast_poisson.c not found in /app/"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Rebuild from source using CMake (out-of-source build)
rm -rf /app/build
mkdir -p /app/build
cd /app/build

cmake .. 2>&1
if [ $? -ne 0 ]; then
    echo "CMake configuration failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

make 2>&1
if [ $? -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Remove stale outputs and run the optimized solver
rm -f /app/results.txt /app/solution.bin
timeout 120 ./fast_poisson
if [ $? -ne 0 ]; then
    echo "Runtime error or timeout"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run verification tests
cd /tests
pytest test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
