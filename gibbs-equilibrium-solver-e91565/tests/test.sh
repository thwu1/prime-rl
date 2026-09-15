#!/usr/bin/env bash

set -u

pip3 install pytest==8.3.4 -q

cd /app

# Build the solver with cmake
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1
make 2>&1
BUILD_RC=$?
cd /app

if [ $BUILD_RC -ne 0 ]; then
    echo "Build failed with exit code $BUILD_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run on all five test problems
for N in 1 2 3 4 5; do
    /app/build/geqsolve "/app/problem_${N}.txt" "/app/results_${N}.txt" || true
done

# Run verification tests
pytest /tests/test_state.py -v --tb=short
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_RC
