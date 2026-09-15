#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Build the OCaml project
dune build 2>/tmp/build_err.txt
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo "Build failed"
    cat /tmp/build_err.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Run the test driver with a timeout to prevent hangs
timeout 120 dune exec ./main.exe 2>/tmp/run_err.txt 1>/tmp/run_out.txt
RUN_RC=$?

cat /tmp/run_out.txt
cat /tmp/run_err.txt >&2

# Run pytest for additional validation
pytest /tests/test_state.py -v 2>/tmp/pytest_err.txt 1>/tmp/pytest_out.txt
PYTEST_RC=$?

cat /tmp/pytest_out.txt
cat /tmp/pytest_err.txt >&2

mkdir -p /logs/verifier

if [ $RUN_RC -eq 0 ] && grep -q "ALL TESTS PASSED" /tmp/run_out.txt && [ $PYTEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
