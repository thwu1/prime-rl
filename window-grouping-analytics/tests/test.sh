#!/bin/bash

pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Start PostgreSQL if not running
pg_ctlcluster 16 main start 2>/dev/null || true
sleep 2

# Create database (ignore error if exists)
psql -U postgres -c "CREATE DATABASE analytics_db;" 2>/dev/null || true

# Load schema (idempotent: uses DROP TABLE IF EXISTS CASCADE)
psql -U postgres -d analytics_db -f /app/schema.sql

# Run tests
RESULT=0
python3 -m pytest /tests/test_state.py -v || RESULT=1

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
