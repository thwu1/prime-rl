#!/bin/bash

set +e

cd /app

# Install project dependencies
npm install --silent 2>&1

# Install test dependencies

# Run the codegen to produce the output from the current generator
npx tsx /app/src/codegen.ts 2>&1

# Run pytest
RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?
echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
