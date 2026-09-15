#!/usr/bin/env bash

pip3 install psycopg2-binary==2.9.10 pytest==8.3.4 -q

# ---------- PostgreSQL startup ----------
# Fix potential permission issues preventing user-id lookups in containers
chmod 644 /etc/passwd /etc/group 2>/dev/null || true

PG_VER=$(ls /usr/lib/postgresql/ 2>/dev/null | sort -V | tail -1)
if [ -z "$PG_VER" ]; then
    echo "PostgreSQL not installed"
    mkdir -p /logs/verifier && echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Create cluster if it was not created during apt install
if [ ! -d "/etc/postgresql/$PG_VER/main" ]; then
    pg_createcluster "$PG_VER" main 2>&1
fi

# Ensure directory ownership
mkdir -p /var/run/postgresql /var/log/postgresql
chown -R postgres:postgres /var/run/postgresql /var/log/postgresql 2>/dev/null || true
chown -R postgres:postgres "/var/lib/postgresql" 2>/dev/null || true

# Configure trust authentication so psql -U postgres works without OS-level user switching
HBA="/etc/postgresql/$PG_VER/main/pg_hba.conf"
if [ -f "$HBA" ]; then
    printf 'local\tall\tall\ttrust\nhost\tall\tall\t127.0.0.1/32\ttrust\nhost\tall\tall\t::1/128\ttrust\n' > "$HBA"
    chown postgres:postgres "$HBA" 2>/dev/null || true
fi

# Start PostgreSQL
pg_ctlcluster "$PG_VER" main start 2>&1 || true

# Wait for PostgreSQL to accept connections (up to 30 seconds)
for i in $(seq 1 30); do
    psql -U postgres -c "SELECT 1" >/dev/null 2>&1 && break
    sleep 1
done

# Verify PostgreSQL is running
if ! psql -U postgres -c "SELECT 1" >/dev/null 2>&1; then
    echo "PostgreSQL failed to start"
    mkdir -p /logs/verifier && echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# ---------- Database setup ----------
psql -U postgres -c "DROP DATABASE IF EXISTS transit_db;" 2>/dev/null
psql -U postgres -c "CREATE DATABASE transit_db;" 2>/dev/null
psql -U postgres -d transit_db -q -f /app/schema.sql 2>&1
psql -U postgres -d transit_db -q -f /app/queries.sql 2>&1

# ---------- Run tests ----------
python3 -m pytest /tests/test_state.py -v 2>&1
PYTEST_EXIT=$?

mkdir -p /logs/verifier

if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
