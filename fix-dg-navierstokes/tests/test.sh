#!/bin/bash

# Install test dependencies (pinned versions)
pip3 install pytest==8.3.4 -q

# Anti-cheat: remove any pre-existing result files
rm -f /app/results.json /app/convergence.json

# Run the verification tests
cd /app
pytest /tests/test_state.py -v
exit_code=$?

# Write reward based on test outcome
mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
