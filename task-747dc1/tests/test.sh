#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app/fredbuf
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1
cmake --build . --parallel 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run internal smoke test
./fredbuf_test 2>&1
SMOKE_EXIT=$?

if [ $SMOKE_EXIT -ne 0 ]; then
    echo "Smoke test failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run external pytest verification
cd /
python3 -m pytest /tests/test_state.py -v 2>&1
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
