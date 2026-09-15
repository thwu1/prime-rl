#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Build using Makefile
make compile 2>&1
COMPILE_RC=$?

if [ $COMPILE_RC -ne 0 ]; then
    echo "Build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run model checker without POR
mkdir -p /app/build
make run > /app/build/output_no_por.txt 2>&1
RUN_RC=$?

if [ $RUN_RC -ne 0 ]; then
    echo "make run failed"
    cat /app/build/output_no_por.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run model checker with POR
make run-por > /app/build/output_por.txt 2>&1
POR_RC=$?

if [ $POR_RC -ne 0 ]; then
    echo "make run-por failed"
    cat /app/build/output_por.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RC
