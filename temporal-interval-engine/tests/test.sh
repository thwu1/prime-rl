#!/bin/bash

# Configure PostgreSQL for trust authentication
PG_HBA=$(find /etc/postgresql -name pg_hba.conf 2>/dev/null | head -1)
if [ -n "$PG_HBA" ]; then
    echo "local all all trust" > "$PG_HBA"
    echo "host all all 127.0.0.1/32 trust" >> "$PG_HBA"
    echo "host all all ::1/128 trust" >> "$PG_HBA"
fi

# Start PostgreSQL
service postgresql start 2>/dev/null || pg_ctlcluster $(ls /etc/postgresql/) main start 2>/dev/null || true

# Wait for PostgreSQL to be ready
for i in $(seq 1 30); do
    pg_isready -U postgres -q 2>/dev/null && break
    sleep 0.5
done

# Create database
psql -U postgres -c "CREATE DATABASE taskdb" 2>/dev/null || true

# Run setup and solution SQL
psql -U postgres -d taskdb -f /app/setup.sql
psql -U postgres -d taskdb -f /app/solution.sql

# Run tests
RESULT=0
pytest /tests/test_state.py -v || RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
