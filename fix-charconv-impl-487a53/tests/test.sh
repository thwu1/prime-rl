#!/usr/bin/env bash

set -u

pip3 install pytest==8.3.4 -q

# Compile the test runner against the candidate implementation
g++ -std=c++17 -O2 -Wall -Wextra \
    -o /tmp/charconv_test_runner \
    /tests/test_runner.cpp /app/charconv.cpp \
    -I/app 2>/tmp/compile_errors.txt

if [ $? -ne 0 ]; then
    echo "Compilation failed:"
    cat /tmp/compile_errors.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
cd /tests
python3 -m pytest test_state.py -v --tb=short 2>&1 | tee /tmp/pytest_output.txt
RESULT=${PIPESTATUS[0]}

mkdir -p /logs/verifier
if [ "$RESULT" -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
