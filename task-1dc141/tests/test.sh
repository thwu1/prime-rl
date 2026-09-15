#!/bin/bash

# Copy Go test file into the raft package
cp /tests/node_test.go /app/raft/node_test.go

# Build the Go test binary
cd /app
go test -c -o /tmp/raft_test ./raft/ 2>&1
BUILD_EXIT=$?

if [ $BUILD_EXIT -ne 0 ]; then
    echo "Go build failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Install pytest and run the Python test wrapper
pip3 install pytest==8.3.4 -q

python3 -m pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
