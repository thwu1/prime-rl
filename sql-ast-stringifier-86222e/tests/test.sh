#!/bin/bash

set +e

cd /app

# Install project dependencies (peggy + typescript)
npm install --ignore-scripts 2>&1

# Ensure directories exist
mkdir -p /app/src/generated

# Generate parser from grammar
npx peggy --format commonjs -o src/generated/parser.js grammar/sql.pegjs 2>&1

# Compile TypeScript
npx tsc 2>&1

# Run the test runner to generate results JSON
node /tests/test_runner.js 2>&1

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run pytest and capture exit code
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
