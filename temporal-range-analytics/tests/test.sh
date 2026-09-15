#!/bin/bash


# Install test dependencies
pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Start PostgreSQL if not running
service postgresql start 2>/dev/null || true

# Wait for PostgreSQL to be ready
for i in $(seq 1 30); do
    pg_isready -U postgres -q && break
    sleep 1
done

# Force a clean database to avoid stale state from prior runs
psql -U postgres -c "DROP DATABASE IF EXISTS taskdb;" 2>/dev/null || true
psql -U postgres -c "CREATE DATABASE taskdb;"

# Load schema and seed data into the fresh database
psql -U postgres -d taskdb -f /app/setup.sql 2>&1

# Drop allocations table in case setup.sql somehow created one
psql -U postgres -d taskdb -c "DROP TABLE IF EXISTS allocations CASCADE;" 2>&1

# Run the migration query (solver must have fixed it)
psql -U postgres -d taskdb -f /app/queries/migration.sql 2>&1 || true

# Run pytest and capture exit code
RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
