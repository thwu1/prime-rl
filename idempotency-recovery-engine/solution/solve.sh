#!/bin/bash

# Install dependencies
pip3 install psycopg2-binary==2.9.10 -q

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

# Ensure database exists with correct schema
psql -U postgres -h 127.0.0.1 -tc "SELECT 1 FROM pg_database WHERE datname = 'idempotency'" | grep -q 1 || \
    psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE idempotency;"
psql -U postgres -h 127.0.0.1 -d idempotency -f /app/schema.sql 2>/dev/null

# Deploy the correct solution over the buggy implementation
cp /solution/idempotency_solution.py /app/idempotency.py
