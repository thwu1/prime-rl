#!/bin/bash

# Start PostgreSQL if not running
pg_ctlcluster 16 main start 2>/dev/null || true
sleep 3

# Wait for PostgreSQL to be ready
for i in $(seq 1 10); do
    pg_isready -q && break
    sleep 1
done

# Apply optimization.sql if it exists (idempotent)
if [ -f /app/optimization.sql ]; then
    psql -U postgres -d postgres_air -f /app/optimization.sql 2>/dev/null || true
fi

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Run tests and capture exit code
EXITCODE=0
python3 -m pytest /tests/test_state.py -v --tb=short || EXITCODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXITCODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXITCODE
