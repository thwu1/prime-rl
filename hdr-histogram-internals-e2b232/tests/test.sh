#!/usr/bin/env bash

set -u

pip3 install pytest==8.3.4 -q

# Build using the project Makefile
cd /app
make build 2>/tmp/make_err.txt
MAKE_EXIT=$?

if [ $MAKE_EXIT -ne 0 ]; then
    echo "Build failed (make build):"
    cat /tmp/make_err.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Verify class files exist in expected location
if [ ! -f /app/classes/HdrHistogram.class ] || [ ! -f /app/classes/HistogramCodec.class ]; then
    echo "Build did not produce expected class files in /app/classes/"
    echo "Contents of /app/classes/ (if exists):"
    ls -la /app/classes/ 2>/dev/null || echo "(directory does not exist)"
    echo "Contents of /app/build/ (if exists):"
    ls -la /app/build/ 2>/dev/null || echo "(directory does not exist)"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
