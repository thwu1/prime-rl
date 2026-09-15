#!/bin/bash

# Build the compiler and generate the filter
cd /app

make clean
make bpf_compiler
if [ $? -ne 0 ]; then
    echo "Compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

make filter.bpf
if [ $? -ne 0 ]; then
    echo "Filter generation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
python3 -m pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
