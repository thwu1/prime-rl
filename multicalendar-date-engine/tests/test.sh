#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app
rm -rf build
mkdir -p build
cd build
cmake .. 2>&1
CMAKE_EXIT=$?
if [ $CMAKE_EXIT -ne 0 ]; then
    echo "CMake configuration failed"
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

cd /tests
python3 -m pytest test_state.py -v --tb=short
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
