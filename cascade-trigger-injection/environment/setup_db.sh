#!/bin/bash
set -ex

PG_VER=$(ls /etc/postgresql/ | sort -V | tail -1)

# Ensure run directory exists (required for socket in Docker)
mkdir -p /run/postgresql && chown postgres:postgres /run/postgresql

# Configure trust authentication for all local connections
echo "local all all trust" > /etc/postgresql/$PG_VER/main/pg_hba.conf
echo "host all all 127.0.0.1/32 trust" >> /etc/postgresql/$PG_VER/main/pg_hba.conf
echo "host all all ::1/128 trust" >> /etc/postgresql/$PG_VER/main/pg_hba.conf

# Enable TCP connections on localhost
sed -i "s/^#listen_addresses.*/listen_addresses = 'localhost'/" /etc/postgresql/$PG_VER/main/postgresql.conf

# Start PostgreSQL
pg_ctlcluster $PG_VER main start

# Wait for PostgreSQL to be fully ready (up to 30 seconds)
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then
        echo "PostgreSQL is ready after ${i}s"
        break
    fi
    sleep 1
done

# Hard verify PostgreSQL is accepting connections
pg_isready

# Create database and load schema with strict error handling
psql -U postgres -c "CREATE DATABASE appdb"
psql -U postgres -d appdb --set ON_ERROR_STOP=on -f /app/schema.sql

# Verify all tables were created and seed data loaded
echo "=== Verifying schema ==="
psql -U postgres -d appdb -c "SELECT 'departments', count(*) FROM departments"
psql -U postgres -d appdb -c "SELECT 'projects', count(*) FROM projects"
psql -U postgres -d appdb -c "SELECT 'tasks', count(*) FROM tasks"
psql -U postgres -d appdb -c "SELECT 'cascade_log', count(*) FROM _cascade_log"
psql -U postgres -d appdb -c "SELECT proname FROM pg_proc WHERE proname IN ('cascade_fk_update','cascade_fk_delete','needs_quoting') ORDER BY proname"

# Stop PostgreSQL cleanly
pg_ctlcluster $PG_VER main stop
echo "=== Schema loaded and verified successfully ==="
