#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q
npm install -g fsh-sushi@3.16.5 2>/dev/null

# Run SUSHI and capture output
cd /app
SUSHI_OUTPUT=$(sushi . 2>&1)
SUSHI_EXIT=$?

# Save SUSHI output for test inspection
echo "$SUSHI_OUTPUT" > /app/sushi_output.txt
echo "$SUSHI_EXIT" > /app/sushi_exit_code.txt

# Run pytest
PYTEST_EXIT=0
python3 -m pytest /tests/test_state.py -v || PYTEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
