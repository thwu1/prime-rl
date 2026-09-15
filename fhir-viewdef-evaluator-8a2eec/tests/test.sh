#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Install Node.js dependencies
npm install --loglevel=error 2>/dev/null

# Verify test data files are present
echo "Test data files found:"
ls -1 testdata/test_*.json 2>/dev/null

# Run the evaluator CLI against all test data files
npx ts-node src/cli.ts run testdata/test_*.json > /app/report.json 2>/app/cli_stderr.txt

CLI_EXIT=$?
echo "CLI exit code: $CLI_EXIT"
cat /app/cli_stderr.txt >&2

# Run pytest verification
RESULT=$(python3 -m pytest /tests/test_state.py -v 2>&1)
PYTEST_EXIT=$?

mkdir -p /logs/verifier

if [ $PYTEST_EXIT -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi

echo "$RESULT"
exit $PYTEST_EXIT
