#!/bin/bash

pip3 install pytest==8.3.4 -q

# Compile TypeScript
cd /app
npm install 2>&1
npx tsc 2>&1
TSC_RESULT=$?

if [ $TSC_RESULT -ne 0 ]; then
    echo "TypeScript compilation failed with exit code $TSC_RESULT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
cd /tests
python3 -m pytest test_state.py -v 2>&1
PYTEST_RESULT=$?

mkdir -p /logs/verifier
if [ $PYTEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_RESULT
