#!/bin/bash

# Install test dependencies - try multiple methods for robustness
export PIP_BREAK_SYSTEM_PACKAGES=1
pip3 install pytest==8.3.4 -q 2>/dev/null \
  || python3 -m pip install pytest==8.3.4 -q 2>/dev/null \
  || (curl -sS https://bootstrap.pypa.io/get-pip.py | python3 2>/dev/null && pip3 install pytest==8.3.4 -q)

# Verify pytest is available
python3 -c "import pytest" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: pytest installation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
cd /app
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
