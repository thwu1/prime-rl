#!/bin/bash

pip3 install psycopg2-binary==2.9.10 -q

# Start PostgreSQL
pg_ctlcluster 16 main start
for i in $(seq 1 15); do
    if pg_isready > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Restore original queries and place the query doctor tool
cp /app/.queries_original.sql /app/queries.sql
cp /solution/query_doctor.py /app/query_doctor.py

# Run the diagnostic tool from /app where the tests expect it
python3 /app/query_doctor.py
