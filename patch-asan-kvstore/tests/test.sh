#!/bin/bash

# Disable LeakSanitizer — it cannot run in container/ptrace environments
export ASAN_OPTIONS=detect_leaks=0

# Install test dependencies

# Rebuild the patched kvstore binary
cd /app
make clean
make
COMPILE_RC=$?

if [ $COMPILE_RC -ne 0 ]; then
    echo "Compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
pytest /tests/test_state.py -v
TEST_RC=$?

mkdir -p /logs/verifier
if [ $TEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_RC
