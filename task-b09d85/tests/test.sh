#!/bin/bash

# Ensure PostgreSQL is running for tests
mkdir -p /var/run/postgresql 2>/dev/null
chown postgres:postgres /var/run/postgresql 2>/dev/null
pg_ctlcluster 16 main start 2>/dev/null || true
sleep 2

# Run pytest
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
