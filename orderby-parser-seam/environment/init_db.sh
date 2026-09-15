#!/bin/bash
set -e

# Configure trust authentication for all local connections
echo "local all all trust" > /etc/postgresql/16/main/pg_hba.conf
echo "host all all 127.0.0.1/32 trust" >> /etc/postgresql/16/main/pg_hba.conf
echo "host all all ::1/128 trust" >> /etc/postgresql/16/main/pg_hba.conf

# Start PostgreSQL
pg_ctlcluster 16 main start

# Wait for PostgreSQL to be ready
for i in $(seq 1 15); do
    if pg_isready > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Create database and load schema
createdb -U postgres analytics
psql -U postgres -d analytics -f /app/schema.sql

# Stop PostgreSQL cleanly
pg_ctlcluster 16 main stop
