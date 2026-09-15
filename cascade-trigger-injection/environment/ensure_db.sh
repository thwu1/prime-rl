#!/bin/bash
# Safety net: ensure PostgreSQL is running and schema is loaded.
# Idempotent — safe to call multiple times.

PG_VER=$(ls /etc/postgresql/ 2>/dev/null | sort -V | tail -1)

# Ensure run directory exists
mkdir -p /run/postgresql 2>/dev/null && chown postgres:postgres /run/postgresql 2>/dev/null || true

# Start PostgreSQL if not running
pg_ctlcluster "$PG_VER" main start 2>/dev/null || true

# Wait for PostgreSQL to accept connections
for i in $(seq 1 20); do
    pg_isready -q 2>/dev/null && break
    sleep 1
done

# Create database if it does not exist
psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'appdb'" 2>/dev/null | grep -q 1 || \
    psql -U postgres -c "CREATE DATABASE appdb" 2>/dev/null

# Load schema if the tasks table is missing (indicates schema was not loaded)
if ! psql -U postgres -d appdb -tc "SELECT 1 FROM pg_tables WHERE tablename = 'tasks' AND schemaname = 'public'" 2>/dev/null | grep -q 1; then
    echo "Schema not found — loading from /app/schema.sql ..."
    psql -U postgres -d appdb --set ON_ERROR_STOP=on -f /app/schema.sql
    echo "Schema loaded."
fi
