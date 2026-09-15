#!/bin/bash

pip3 install pytest==8.3.4 -q

# Install npm dependencies and compile TypeScript
cd /app
npm install 2>/dev/null
npx tsc 2>&1
TSC_EXIT=$?

cd /
PYTEST_EXIT=1
if [ $TSC_EXIT -eq 0 ]; then
    python3 -m pytest /tests/test_state.py -v
    PYTEST_EXIT=$?
else
    echo "TypeScript compilation failed (exit code $TSC_EXIT)"
fi

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
