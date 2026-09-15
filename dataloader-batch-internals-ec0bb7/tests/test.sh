#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

cd /app
npm install 2>/dev/null

# Copy test file into app test directory
mkdir -p /app/src/__tests__
cp /tests/dataloader.test.ts /app/src/__tests__/dataloader.test.ts

# Run pytest
pytest /tests/test_state.py -v 2>&1
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
