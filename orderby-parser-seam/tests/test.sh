#!/bin/bash

pip3 install pytest==8.3.4 psycopg2-binary==2.9.10 -q

# Start PostgreSQL
pg_ctlcluster 16 main start
for i in $(seq 1 15); do
    if pg_isready > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Restore original queries to ensure the tool works from scratch
cp /app/.queries_original.sql /app/queries.sql

# Run tests
cd /app
pytest /tests/test_state.py -v
EXIT_CODE=$?

# Write reward
mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
