#!/bin/bash

pip3 install pytest==8.3.4 -q

# Apply optimize.sql to a fresh copy of the original database
cp /app/.original.db /tmp/test_optimized.db
sqlite3 /tmp/test_optimized.db < /app/optimize.sql 2>/tmp/optimize_stderr.txt
APPLY_EXIT=$?

if [ $APPLY_EXIT -ne 0 ]; then
    echo "ERROR: optimize.sql failed to apply (exit code $APPLY_EXIT)"
    cat /tmp/optimize_stderr.txt
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
cd /app
python3 -m pytest /tests/test_state.py -v 2>&1
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
