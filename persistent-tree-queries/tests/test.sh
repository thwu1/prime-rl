#!/bin/bash

pip3 install pytest==8.3.4 -q

# Extract data from SQLite database to flat format for reference solver
python3 /tests/extract_input.py
if [ $? -ne 0 ]; then
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    echo "Data extraction failed"
    exit 1
fi

# Compile reference solution
g++ -O2 -std=c++17 -o /tests/reference /tests/reference.cpp
if [ $? -ne 0 ]; then
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    echo "Reference compilation failed"
    exit 1
fi

# Generate expected output using reference
/tests/reference < /tests/flat_input.txt > /tests/expected_output.txt
if [ $? -ne 0 ]; then
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    echo "Reference execution failed"
    exit 1
fi

# Run pytest
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
