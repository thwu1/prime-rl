#!/bin/bash

# Ensure ir and codegen modules are findable regardless of /app/ state
export PYTHONPATH=/opt/son_ir:/app:${PYTHONPATH:-}

# Install test dependencies

# Verify gcc is available (needed for native execution tests)
gcc --version > /dev/null 2>&1 || { echo "gcc not found"; exit 1; }

# Run tests
cd /app
python3 -m pytest /tests/test_state.py -v
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
