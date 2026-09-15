#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Ensure /etc/passwd is readable (container may restrict it)
chmod 644 /etc/passwd 2>/dev/null || true

# Detect PostgreSQL version
PG_VERSION=$(ls /etc/postgresql/ 2>/dev/null | sort -rn | head -1)
if [ -z "$PG_VERSION" ]; then
    echo "PostgreSQL not installed" >&2
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

PG_CONF="/etc/postgresql/$PG_VERSION/main"

# Ensure trust authentication is configured
echo "local all all trust" > "$PG_CONF/pg_hba.conf"
echo "host all all 127.0.0.1/32 trust" >> "$PG_CONF/pg_hba.conf"
echo "host all all ::1/128 trust" >> "$PG_CONF/pg_hba.conf"

# Remove stale PID files if any
rm -f /var/run/postgresql/*.pid 2>/dev/null || true

# Start PostgreSQL
pg_ctlcluster "$PG_VERSION" main start 2>&1 || true

# Wait for PostgreSQL to be ready
PG_READY=0
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then
        PG_READY=1
        break
    fi
    sleep 1
done

if [ "$PG_READY" -ne 1 ]; then
    echo "PostgreSQL failed to start" >&2
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Create test database and set up test data (trust auth, no sudo needed)
psql -U postgres -c "CREATE DATABASE testdb;" 2>/dev/null || true
psql -U postgres -d testdb -f /tests/setup_test_db.sql

# Run pytest
cd /app
RESULT=0
pytest /tests/test_state.py -v --tb=short 2>&1 || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
