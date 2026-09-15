#!/bin/bash

# Kill any existing Flask process to avoid port conflicts
pkill -f "python3 /app/server.py" 2>/dev/null || true
sleep 1

# Start PostgreSQL
service postgresql start 2>/dev/null || true
for i in $(seq 1 30); do
    pg_isready -h 127.0.0.1 -q 2>/dev/null && break
    sleep 1
done

# Create audit database and table
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE cds_audit;" 2>/dev/null
psql -h 127.0.0.1 -U postgres -d cds_audit -c "
CREATE TABLE IF NOT EXISTS decision_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    patient_id TEXT NOT NULL,
    hook_instance TEXT NOT NULL,
    cards_count INTEGER NOT NULL,
    max_severity TEXT NOT NULL,
    request_hash TEXT NOT NULL
);" 2>/dev/null

# Restart nginx to pick up any config changes
service nginx restart 2>/dev/null || service nginx start 2>/dev/null || true

# Run tests
pytest_exit=0
python3 -m pytest /tests/test_state.py -v --tb=short || pytest_exit=$?

mkdir -p /logs/verifier
if [ $pytest_exit -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $pytest_exit
