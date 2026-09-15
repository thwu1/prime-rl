#!/bin/bash

pip3 install pytest==8.3.4 -q

# Ensure lalr_gen is executable if it exists
chmod +x /app/lalr_gen 2>/dev/null

# Attempt the build before running tests
cd /app && make all 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "make all failed with exit code $BUILD_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
