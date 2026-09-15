#!/bin/bash

# Install test dependencies (PIP_BREAK_SYSTEM_PACKAGES=1 is set in Dockerfile env)
pip3 install pytest==8.3.4 -q 2>&1 || python3 -m pip install pytest==8.3.4 -q 2>&1

# Run the proof manager to generate signoff report
cd /app
python3 /app/proof_mgr.py

# Run tests
python3 -m pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
