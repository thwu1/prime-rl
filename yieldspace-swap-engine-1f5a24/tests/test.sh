#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app && npm install --silent 2>/dev/null

# Run verify.ts to generate test data
npx tsx src/verify.ts > /tmp/verify_output.json 2>/tmp/verify_errors.txt
VERIFY_EXIT=$?

if [ $VERIFY_EXIT -ne 0 ]; then
    echo "verify.ts failed with exit code $VERIFY_EXIT"
    cat /tmp/verify_errors.txt
    echo '{"error": "verify.ts execution failed"}' > /tmp/verify_output.json
fi

# Run pytest
pytest /tests/test_state.py -v
PYTEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
