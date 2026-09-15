#!/bin/bash

pip3 install pytest==8.3.4 -q

# Try running via make (may fail if Makefile isn't fixed yet)
cd /app
make all 2>&1 || true

# Fallback: run analyzer directly if results are missing
if [ ! -f /app/results/simple_fork_join.json ]; then
    python3 /app/analyzer.py /app/programs/*.json 2>&1 || true
fi

# Run tests and capture exit code
pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RESULT
