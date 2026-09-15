#!/bin/bash

pip3 install psycopg2-binary==2.9.10 -q

# Start PostgreSQL if not already running
pg_ctlcluster 16 main start 2>/dev/null || true

# Wait until PostgreSQL is accepting connections
for _i in $(seq 1 30); do
    pg_isready -q 2>/dev/null && break
    sleep 1
done

# Create user and database (trust auth — no password needed)
psql -U postgres -c "CREATE USER cdc WITH PASSWORD 'cdc' SUPERUSER;" 2>/dev/null || true
psql -U postgres -c "DROP DATABASE IF EXISTS cdc;" 2>/dev/null || true
psql -U postgres -c "CREATE DATABASE cdc OWNER cdc;" 2>/dev/null || true

# Load seed data
psql -U cdc -d cdc -f /app/seed.sql > /dev/null 2>&1

# Run the DDL parser to generate reconstruct.sql
python3 /solution/parse_ddl.py

# Verify it worked
psql -U cdc -d cdc -c "SELECT count(*) AS total_columns FROM schema_state;"
