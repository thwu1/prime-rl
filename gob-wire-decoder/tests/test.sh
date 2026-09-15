#!/bin/bash

pip3 install pytest==8.3.4 -q

# Build and run the test generator to produce fixtures
cd /app
go run /app/generate_tests.go 2>&1
GEN_EXIT=$?
if [ $GEN_EXIT -ne 0 ]; then
    echo "ERROR: Test generator failed with exit code $GEN_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Verify fixture count
FIXTURE_COUNT=$(ls /app/testdata/*.gob 2>/dev/null | wc -l)
echo "Found $FIXTURE_COUNT .gob fixture files"
if [ "$FIXTURE_COUNT" -lt 27 ]; then
    echo "ERROR: Expected at least 27 fixtures, found $FIXTURE_COUNT"
    echo "Files in testdata:"
    ls -la /app/testdata/ 2>/dev/null
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Build the decoder (agent may have already built it, but rebuild to be sure)
cd /app/gobdecode
go build -o /app/gobdecode/gobdecode . 2>&1
BUILD_EXIT=$?
if [ $BUILD_EXIT -ne 0 ]; then
    echo "ERROR: Decoder build failed with exit code $BUILD_EXIT"
fi

# Run pytest
cd /app
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
