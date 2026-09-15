#!/bin/bash

# Ensure PostgreSQL runtime directory exists
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

# Start PostgreSQL if not already running
PG_VERSION=$(ls /etc/postgresql/ | head -1)
rm -f "/var/lib/postgresql/${PG_VERSION}/main/postmaster.pid" 2>/dev/null || true

if ! pg_isready -q 2>/dev/null; then
    pg_ctlcluster ${PG_VERSION} main start 2>/dev/null || true
    for i in $(seq 1 30); do
        if pg_isready -q 2>/dev/null; then break; fi
        sleep 1
    done
fi

# Verify PostgreSQL is accepting connections to the database
for i in $(seq 1 15); do
    if psql -U postgres -d alien_signals -c "SELECT 1" >/dev/null 2>&1; then break; fi
    sleep 1
done

# Install test dependencies
pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

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
