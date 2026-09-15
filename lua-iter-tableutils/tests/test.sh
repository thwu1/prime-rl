#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

# Copy test runner to app directory for execution
cp /tests/test_runner.lua /app/test_runner.lua

cd /app

pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
