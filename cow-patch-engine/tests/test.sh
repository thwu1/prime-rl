#!/usr/bin/env bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Install project dependencies and compile
cd /app && npm install && npx tsc

# Run tests
RESULT=0
pytest /tests/test_state.py -v || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ "$RESULT" -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
