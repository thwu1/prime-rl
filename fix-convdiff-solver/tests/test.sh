#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Build the solver from agent's (potentially modified) source
cd /app
rm -rf build
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1
BUILD_EXIT=$?
if [ $BUILD_EXIT -ne 0 ]; then
    echo "CMake configure failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

cmake --build . 2>&1
BUILD_EXIT=$?
if [ $BUILD_EXIT -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the solver (may exit non-zero if not all configs pass internally)
./solve_convdiff
echo "Solver exited with code $?"

# Run verification tests
pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
