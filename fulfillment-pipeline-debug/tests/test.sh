#!/bin/bash

# Install test dependencies

# Detect PostgreSQL version and configure trust auth
PG_VER=$(ls /etc/postgresql/ | head -1)
PG_HBA="/etc/postgresql/$PG_VER/main/pg_hba.conf"
echo "local all all trust" > "$PG_HBA"
echo "host all all 127.0.0.1/32 trust" >> "$PG_HBA"
echo "host all all ::1/128 trust" >> "$PG_HBA"

# Start PostgreSQL (ignore if already running)
pg_ctlcluster "$PG_VER" main start 2>/dev/null || true
sleep 2

# Create a fresh database
psql -U postgres -c "DROP DATABASE IF EXISTS fulfillment_analytics" 2>/dev/null || true
psql -U postgres -c "CREATE DATABASE fulfillment_analytics"

# Load schema
psql -U postgres -d fulfillment_analytics -f /app/schema.sql -q

# Generate and load deterministic data
python3 /app/generate_data.py | psql -U postgres -d fulfillment_analytics -q

# Execute the analytics SQL (creates the views)
psql -U postgres -d fulfillment_analytics -f /app/analytics.sql
SQL_EXIT=$?

if [ $SQL_EXIT -ne 0 ]; then
    echo "ERROR: analytics.sql failed to execute"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run pytest
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
