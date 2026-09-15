#!/bin/bash

pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Start PostgreSQL if not already running
pg_ctlcluster 16 main start 2>/dev/null || true
pg_isready -U postgres -t 30

# Run tests and capture exit code
pytest /tests/test_state.py -v
RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
