#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Ensure terminal.py is accessible in /app/
cp /opt/task_lib/terminal.py /app/terminal.py 2>/dev/null || true

export PYTHONPATH="/app:/opt/task_lib:${PYTHONPATH}"
export TERM=xterm-256color

# Run tests
cd /app
python3 -m pytest /tests/test_state.py -v --tb=short
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
