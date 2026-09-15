#!/bin/bash

export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# Install test dependencies and ensure playwright browsers are available

# Run the probe if report doesn't exist yet (agent may have already run it)
if [ ! -f /app/output/report.json ]; then
    cd /app
    python3 /app/probe.py 2>&1 || true
fi

# Run verification tests
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
