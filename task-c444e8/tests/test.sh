#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Ensure socket directory and start PostgreSQL
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql
service postgresql start 2>/dev/null || true
sleep 3

# Apply fix.sql if it exists
if [ -f /app/fix.sql ]; then
    psql -U postgres -d benchdb -f /app/fix.sql 2>&1 || true
    sleep 2
fi

# Run tests
cd /tests
python3 -m pytest test_state.py -v
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
