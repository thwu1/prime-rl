#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 duckdb==1.2.1 -q

# Run the agent's repair script if output doesn't exist yet
if [ ! -f /app/output.txt ]; then
    if [ -f /app/repair.sh ]; then
        cd /app && bash /app/repair.sh
    fi
fi

# Run tests
cd /app
pytest /tests/test_state.py -v
exit_code=$?

# Write reward
mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
