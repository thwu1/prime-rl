#!/bin/bash

pip3 install psycopg2-binary==2.9.10 -q

# Configure PostgreSQL for trust authentication
PG_HBA=$(find /etc/postgresql -name pg_hba.conf 2>/dev/null | head -1)
if [ -n "$PG_HBA" ]; then
    echo "local all all trust" > "$PG_HBA"
    echo "host all all 127.0.0.1/32 trust" >> "$PG_HBA"
    echo "host all all ::1/128 trust" >> "$PG_HBA"
fi

# Start PostgreSQL
service postgresql start 2>/dev/null || pg_ctlcluster $(ls /etc/postgresql/) main start 2>/dev/null || true

# Wait for PostgreSQL to be ready
for i in $(seq 1 30); do
    pg_isready -U postgres -q 2>/dev/null && break
    sleep 0.5
done

# Create database
psql -U postgres -c "CREATE DATABASE taskdb" 2>/dev/null || true

# Run setup
psql -U postgres -d taskdb -f /app/setup.sql

# Write the correct solution
cp /solution/correct_solution.sql /app/solution.sql

# Apply solution
psql -U postgres -d taskdb -f /app/solution.sql
