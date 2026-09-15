#!/bin/bash

# Ensure PostgreSQL is running
PG_VER=$(ls /etc/postgresql/ 2>/dev/null | head -1)
if [ -n "$PG_VER" ]; then
    rm -f "/var/run/postgresql/$PG_VER-main.pid" 2>/dev/null
    rm -f /var/run/postgresql/.s.PGSQL.5432* 2>/dev/null
    mkdir -p /var/run/postgresql
    chown postgres:postgres /var/run/postgresql
    pg_ctlcluster "$PG_VER" main start 2>/dev/null || true
    for i in $(seq 1 30); do
        pg_isready -q 2>/dev/null && break
        sleep 1
    done
fi

# Install test dependencies
pip3 install pytest==8.3.4 psycopg2-binary==2.9.9 -q

# Run tests
cd /app
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
