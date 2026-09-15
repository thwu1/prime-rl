#!/bin/bash

pip3 install pytest==8.3.4 -q

# Build
make -C /app
BUILD_RESULT=$?

if [ $BUILD_RESULT -ne 0 ]; then
    echo "Compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Ensure shared library is findable at runtime
export LD_LIBRARY_PATH=/app:${LD_LIBRARY_PATH:-}

# Run tests
pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
