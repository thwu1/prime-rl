#!/bin/bash

# Install test dependencies

# Ensure /etc/passwd is readable for UID lookups
chmod 644 /etc/passwd 2>/dev/null || true

# Ensure PostgreSQL runtime directories exist
mkdir -p /var/run/postgresql /var/log/postgresql
chown -R postgres:postgres /var/run/postgresql /var/log/postgresql 2>/dev/null || true

# Start PostgreSQL if not already running
if ! pg_isready -h 127.0.0.1 -q 2>/dev/null; then
    pg_ctlcluster 16 main start 2>&1 || true
    for i in $(seq 1 30); do
        pg_isready -h 127.0.0.1 -q 2>/dev/null && break
        sleep 1
    done
fi

# Recreate database for clean test state
psql -U postgres -h 127.0.0.1 -c "DROP DATABASE IF EXISTS idempotency;" 2>/dev/null
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE idempotency;"
psql -U postgres -h 127.0.0.1 -d idempotency -f /app/schema.sql

# Run tests
cd /app
pytest /tests/test_state.py -v
exit_code=$?

# Write reward
mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
