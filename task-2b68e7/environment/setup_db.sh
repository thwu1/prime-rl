#!/bin/bash
set -e

PG_VERSION=$(ls /etc/postgresql/ | head -1)

# Ensure runtime directories exist
mkdir -p /var/run/postgresql /var/log/postgresql
chown postgres:postgres /var/run/postgresql /var/log/postgresql

# Remove stale PID file if present
rm -f "/var/lib/postgresql/${PG_VERSION}/main/postmaster.pid"

# Stop PostgreSQL if auto-started during package installation
pg_ctlcluster ${PG_VERSION} main stop 2>/dev/null || true

# Configure trust authentication
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"
echo 'local all all trust' > "$PG_HBA"
echo 'host all all 127.0.0.1/32 trust' >> "$PG_HBA"
echo 'host all all ::1/128 trust' >> "$PG_HBA"

# Start PostgreSQL with updated auth config
pg_ctlcluster ${PG_VERSION} main start
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then break; fi
    sleep 1
done
pg_isready -q || { echo "PostgreSQL failed to start"; exit 1; }

# Create database, load schema and data
createdb -U postgres alien_signals 2>/dev/null || true
psql -U postgres -d alien_signals -f /tmp/init.sql

# Create root superuser for convenience
psql -U postgres -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='root') THEN CREATE ROLE root LOGIN SUPERUSER; END IF; END \$\$;"

# Verify data loaded
COUNT=$(psql -U postgres -d alien_signals -t -A -c "SELECT COUNT(*) FROM signals;")
echo "Signals loaded: ${COUNT}"
[ "${COUNT}" -ge 8 ] || { echo "ERROR: Data verification failed, expected >= 8 signals"; exit 1; }

# Force checkpoint to flush all WAL to disk
psql -U postgres -c "CHECKPOINT;"

# Stop PostgreSQL cleanly with fast mode
pg_ctlcluster ${PG_VERSION} main stop -- -m fast

# Remove stale PID if stop left one behind
rm -f "/var/lib/postgresql/${PG_VERSION}/main/postmaster.pid"
