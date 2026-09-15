#!/usr/bin/env bash

set -u

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Install Node.js dependencies for running TypeScript
cd /app && npm install --save-dev tsx@4.19.4 typescript@5.7.3 2>&1 | tail -1

# Run pytest
RESULT=0
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1 || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ "$RESULT" -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
