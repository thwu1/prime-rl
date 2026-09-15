#!/bin/bash

pip3 install pytest==8.3.4 -q

# Compile Java
cd /app && make
COMPILE_STATUS=$?
if [ $COMPILE_STATUS -ne 0 ]; then
    echo "Compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
python3 -m pytest /tests/test_state.py -v
TEST_STATUS=$?

mkdir -p /logs/verifier
if [ $TEST_STATUS -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_STATUS
