#!/bin/bash


set -u

cd /app

# Install project dependencies
npm install --quiet 2>/dev/null

# Compile TypeScript
npx tsc 2>/tmp/tsc_errors.txt
if [ $? -ne 0 ]; then
  echo "TypeScript compilation failed:"
  cat /tmp/tsc_errors.txt
  mkdir -p /logs/verifier
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi

exit 0
