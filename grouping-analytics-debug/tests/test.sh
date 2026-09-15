#!/bin/bash

pg_ctlcluster 16 main start 2>/dev/null || true
sleep 2

psql -U postgres -c "DROP DATABASE IF EXISTS analytics_db" 2>/dev/null || true
psql -U postgres -c "CREATE DATABASE analytics_db"

psql -U postgres -d analytics_db -f /app/setup.sql

psql -U postgres -d analytics_db -f /app/analytics.sql 2>&1

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
