#!/bin/bash

# Start PostgreSQL if not running
pg_ctlcluster 16 main start 2>/dev/null || true
sleep 3
for i in $(seq 1 10); do
    pg_isready -q && break
    sleep 1
done

# Generate the optimization SQL by analyzing the database
python3 /solution/optimize.py

# Apply the optimization
psql -U postgres -d postgres_air -f /app/optimization.sql
