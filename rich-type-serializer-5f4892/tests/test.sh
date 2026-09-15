#!/bin/bash


pip3 install pytest==8.3.4 -q

# Install npm dependencies
cd /app && npm install --silent 2>/dev/null

# Copy authoritative test suite to prevent tampering
cp /tests/test_suite.ts /app/src/index.test.ts

# Run pytest verification
cd /tests
python3 -m pytest test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
