#!/bin/bash

pip3 install pytest==8.3.4 -q

# Compile C reference from source
gcc -O2 -o /app/c_src/record_processor /app/c_src/record_processor.c
if [ $? -ne 0 ]; then
    echo "C compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Build Rust from source
cd /app/rust_src && cargo build --release 2>&1
if [ $? -ne 0 ]; then
    echo "Rust compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

cd /app

# Run pytest
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
