#!/bin/bash

pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Start PostgreSQL if not already running
pg_ctlcluster 16 main start 2>/dev/null || true

# Wait until PostgreSQL is accepting connections
for _i in $(seq 1 30); do
    pg_isready -q 2>/dev/null && break
    sleep 1
done

# Create user and database (trust auth — no password needed for psql -U postgres)
psql -U postgres -c "CREATE USER cdc WITH PASSWORD 'cdc' SUPERUSER;" 2>/dev/null || true
psql -U postgres -c "DROP DATABASE IF EXISTS cdc;" 2>/dev/null || true
psql -U postgres -c "CREATE DATABASE cdc OWNER cdc;" 2>/dev/null || true

# Load seed data
psql -U cdc -d cdc -f /app/seed.sql > /dev/null 2>&1

# Load and execute the solver's reconstruct.sql
psql -U cdc -d cdc -f /app/reconstruct.sql > /dev/null 2>&1

# Run pytest
RESULT=$(python3 -m pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
echo "$RESULT"
exit $EXIT_CODE
