#!/bin/bash

# Find PostgreSQL version
PG_VERSION=$(ls /etc/postgresql/ 2>/dev/null | head -1)

# Ensure socket directory exists and is accessible
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

# Start PostgreSQL
pg_ctlcluster "$PG_VERSION" main start 2>/dev/null || true

# Wait for PostgreSQL to be ready (TCP)
for i in $(seq 1 30); do
    pg_isready -h 127.0.0.1 -q && break
    sleep 1
done

# Load base data if database doesn't exist
psql -U postgres -h 127.0.0.1 -d exercises -c 'SELECT 1 FROM cd.bookings LIMIT 1' 2>/dev/null
if [ $? -ne 0 ]; then
    dropdb -U postgres -h 127.0.0.1 exercises 2>/dev/null || true
    psql -U postgres -h 127.0.0.1 -f /app/clubdata.sql
fi

# Copy the fixed analytics SQL
cp /solution/analytics_fixed.sql /app/analytics.sql

# Apply the fixed views and function
psql -U postgres -h 127.0.0.1 -d exercises -f /app/analytics.sql
