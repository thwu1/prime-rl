#!/bin/bash
# Build-time database setup: creates the atlas user, databases, and the
# intentionally broken migration state that the agent must recover from.
# This script runs once during Docker build (RUN step) and is deleted afterward.
set -e

PG_VER=$(ls /etc/postgresql/ | head -1)

# Configure trust authentication
cp /tmp/pg_hba.conf "/etc/postgresql/$PG_VER/main/pg_hba.conf"
chown postgres:postgres "/etc/postgresql/$PG_VER/main/pg_hba.conf"

# Ensure PostgreSQL listens on localhost
PG_CONF="/etc/postgresql/$PG_VER/main/postgresql.conf"
grep -q "^listen_addresses" "$PG_CONF" || echo "listen_addresses = 'localhost'" >> "$PG_CONF"

# Start PostgreSQL
pg_ctlcluster "$PG_VER" main start

# Wait for PostgreSQL to accept connections
for i in $(seq 1 30); do
    pg_isready -q 2>/dev/null && break
    sleep 1
done

# Create atlas user and application databases
psql -U postgres -c "CREATE USER atlas WITH PASSWORD 'atlas' SUPERUSER;"
psql -U postgres -c "CREATE DATABASE appdb OWNER atlas;"
psql -U postgres -c "CREATE DATABASE devdb OWNER atlas;"

# Verify connectivity
psql -h localhost -U atlas -d appdb -c "SELECT 1;" > /dev/null 2>&1

cd /app

# Generate migration directory integrity hash
atlas migrate hash --dir file://migrations

# Apply first 2 migrations (create customers, products, orders)
atlas migrate apply 2 --env local

# Insert seed data before migration 3 runs
psql -h localhost -U atlas -d appdb -f /tmp/seed.sql

# Apply migration 3 — will PARTIALLY FAIL because:
#   txmode=none means each statement runs independently (no tx rollback)
#   Statement 1: CREATE TABLE order_items        → SUCCEEDS
#   Statement 2: ALTER TABLE customers ADD phone  → SUCCEEDS
#   Statement 3: ALTER TABLE orders ADD shipping_address NOT NULL → FAILS
#     (table has rows, NOT NULL without DEFAULT is impossible)
#   Statement 4: CREATE INDEX CONCURRENTLY ...    → NEVER RUNS
atlas migrate apply 1 --env local 2>&1 || true

# Simulate unauthorized DBA manual interventions (schema drift)
psql -h localhost -U atlas -d appdb -f /tmp/drift.sql

# Stop PostgreSQL cleanly
pg_ctlcluster "$PG_VER" main stop

# Clean up stale PID/socket
rm -f "/var/run/postgresql/$PG_VER-main.pid"
rm -f /var/run/postgresql/.s.PGSQL.5432*
