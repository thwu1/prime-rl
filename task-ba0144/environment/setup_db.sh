#!/bin/bash
set -e

# Ensure socket directory exists with correct permissions
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

# Ensure log directory exists with correct permissions
mkdir -p /var/log/postgresql
chown postgres:postgres /var/log/postgresql

# Remove any stale PID/socket files
rm -f /var/lib/postgresql/16/main/postmaster.pid
rm -f /var/run/postgresql/16-main.pid
rm -f /var/run/postgresql/.s.PGSQL.*

# Start PostgreSQL with -w (wait for startup) and 60s timeout
su -s /bin/sh postgres -c '/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/16/main -o "-c config_file=/etc/postgresql/16/main/postgresql.conf" -l /var/log/postgresql/pg_setup.log -w -t 60 start'

# Double-check with pg_isready
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then
        break
    fi
    sleep 1
done

# Create role and database
psql -U postgres -c "CREATE ROLE omop WITH LOGIN SUPERUSER;"
psql -U postgres -c "CREATE DATABASE omop OWNER omop;"
psql -U postgres -d omop -f /tmp/init_schema.sql
psql -U postgres -d omop -f /tmp/init_data.sql

# Stop PostgreSQL cleanly with -w (wait for shutdown)
su -s /bin/sh postgres -c '/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/16/main -m fast -w stop'

# Explicitly remove PID and socket files to prevent stale state in image
rm -f /var/lib/postgresql/16/main/postmaster.pid
rm -f /var/run/postgresql/16-main.pid
rm -f /var/run/postgresql/.s.PGSQL.*
