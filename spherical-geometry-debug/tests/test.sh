#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

npm install --silent 2>/dev/null
npx tsc
TSC_RESULT=$?

if [ $TSC_RESULT -ne 0 ]; then
    echo "TypeScript compilation failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

pytest /tests/test_state.py -v
TEST_RESULT=$?

mkdir -p /logs/verifier
if [ $TEST_RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_RESULT
