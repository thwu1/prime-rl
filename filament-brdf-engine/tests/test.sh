#!/bin/bash


pip3 install pytest==8.3.4 -q

# Build the project
cd /app
rm -rf build
mkdir -p build
cd build
cmake .. 2>&1
make 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run the evaluation driver
cd /app
python3 driver.py 2>&1
DRIVER_EXIT=$?

if [ $DRIVER_EXIT -ne 0 ]; then
    echo "Driver failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
