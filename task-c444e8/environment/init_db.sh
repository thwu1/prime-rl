#!/bin/bash
set -e

PG_VERSION=$(ls /etc/postgresql/ | head -1)
PGBIN="/usr/lib/postgresql/${PG_VERSION}/bin"
PGDATA="/var/lib/postgresql/${PG_VERSION}/main"
PGCONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"

# Ensure socket directory exists with correct permissions
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

# Start PostgreSQL as postgres user (pg_ctl requires running as the DB owner)
su -s /bin/bash - postgres -c "${PGBIN}/pg_ctl -D ${PGDATA} -o '-c config_file=${PGCONF}' -l /tmp/pg_init.log start"

# Wait for PostgreSQL to be ready
for i in $(seq 1 30); do
    if pg_isready > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Run psql as root (NOT via su) to avoid NSS UID lookup issues in podman builds.
# pg_hba.conf is configured with 'trust' auth, so root can connect as any PG user.
psql -U postgres -c 'CREATE DATABASE benchdb;'
psql -U postgres -d benchdb -f /tmp/setup.sql

# Stop PostgreSQL cleanly
su -s /bin/bash - postgres -c "${PGBIN}/pg_ctl -D ${PGDATA} -m fast stop"
