#!/bin/bash

# Install test dependencies

# Run the agent's pipeline if it exists
cd /app
if [ -f /app/pipeline.sh ]; then
    chmod +x /app/pipeline.sh
    bash /app/pipeline.sh 2>&1 || true
fi

# Run verification tests
RESULT=$(python3 -m pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

echo "$RESULT"

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
