#!/bin/bash

cd /app

echo "=== Building proforma_parse ==="
cargo build --release 2>&1
BUILD_EXIT=$?
if [ $BUILD_EXIT -ne 0 ]; then
    echo "Build failed with exit code $BUILD_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

echo "=== Running proforma_parse ==="
./target/release/proforma_parse /app/input.txt /app/output.json 2>&1
RUN_EXIT=$?
if [ $RUN_EXIT -ne 0 ]; then
    echo "Runtime failed with exit code $RUN_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

echo "=== Running tests ==="
RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?
echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
