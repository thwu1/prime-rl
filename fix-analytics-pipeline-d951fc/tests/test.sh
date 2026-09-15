#!/bin/bash

pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Find PostgreSQL version
PG_VERSION=$(ls /etc/postgresql/ 2>/dev/null | head -1)

# Ensure socket directory exists and is accessible
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

# Start PostgreSQL
pg_ctlcluster "$PG_VERSION" main start 2>/dev/null || true

# Wait for PostgreSQL to be ready (TCP)
for i in $(seq 1 30); do
    pg_isready -h 127.0.0.1 -q && break
    sleep 1
done

# Load base data if database doesn't exist or is broken
psql -U postgres -h 127.0.0.1 -d exercises -c 'SELECT 1 FROM cd.bookings LIMIT 1' 2>/dev/null
if [ $? -ne 0 ]; then
    dropdb -U postgres -h 127.0.0.1 exercises 2>/dev/null || true
    psql -U postgres -h 127.0.0.1 -f /app/clubdata.sql 2>/dev/null
fi

# Always re-apply analytics views/functions from the solver's file
psql -U postgres -h 127.0.0.1 -d exercises -f /app/analytics.sql 2>/dev/null

# Run tests
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
