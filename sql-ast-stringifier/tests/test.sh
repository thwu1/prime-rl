#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Install Node.js dependencies for the stringifier
cd /app && npm install 2>&1

# Run tests
RESULT=0
python3 -m pytest /tests/test_state.py -v || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
