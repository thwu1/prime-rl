#!/bin/bash

set -e

# Configure trust authentication before starting PostgreSQL
cat > /etc/postgresql/16/main/pg_hba.conf << 'HBA'
local all all trust
host  all all 127.0.0.1/32 trust
host  all all ::1/128      trust
HBA

# Ensure socket directory exists with correct ownership
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

# Start PostgreSQL
pg_ctlcluster 16 main start 2>/dev/null || pg_ctlcluster 16 main restart 2>/dev/null || true

# Wait for PostgreSQL to accept connections
for i in $(seq 1 30); do
    pg_isready -U postgres -q && break
    sleep 1
done

# Create database (idempotent)
dropdb -U postgres --if-exists temporal_test 2>/dev/null || true
createdb -U postgres temporal_test

# Apply seed schema
psql -U postgres -d temporal_test -f /app/seed.sql

# Deploy the solution
cp /solution/temporal_solution.sql /app/temporal.sql

# Apply temporal functions
psql -U postgres -d temporal_test -f /app/temporal.sql
