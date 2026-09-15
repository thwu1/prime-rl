#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run pytest on the verification tests
cd /app
pytest /tests/test_state.py -v --tb=short
exit_code=$?

# Write reward based on test outcome
mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
