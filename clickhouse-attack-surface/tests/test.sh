#!/bin/bash

# Ensure PostgreSQL is running
PG_MAJOR=$(ls /etc/postgresql/ 2>/dev/null | sort -n | tail -1)
if [ -z "$PG_MAJOR" ]; then
    PG_MAJOR=16
fi

if ! pg_isready -q 2>/dev/null; then
    pg_ctlcluster "$PG_MAJOR" main start
    for i in $(seq 1 30); do
        pg_isready -q 2>/dev/null && break
        sleep 1
    done
fi

# Install test dependencies
pip3 install pytest==8.3.4 psycopg2-binary==2.9.9 -q

# Run tests
cd /tests
pytest test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
