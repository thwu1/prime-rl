#!/bin/bash

# Install test dependencies (Playwright is pre-installed in the Docker image)
pip3 install pytest==8.3.4 -q

# Ensure Playwright browser binary is present (no-op if already installed, no apt needed)
python3 -m playwright install chromium 2>&1 | tail -1

# Run the agent's probe to generate report.json
cd /app
if [ -f probe.py ]; then
    python3 probe.py 2>&1
else
    echo "ERROR: /app/probe.py not found"
fi

# Run verification tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
