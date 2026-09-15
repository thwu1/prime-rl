#!/bin/bash

# Ensure socket directory exists with correct permissions
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

# Ensure log directory exists with correct permissions
mkdir -p /var/log/postgresql
chown postgres:postgres /var/log/postgresql

# Ensure /tmp is writable
chmod 1777 /tmp

# Remove stale PID and socket files left from docker build
rm -f /var/lib/postgresql/16/main/postmaster.pid
rm -f /var/run/postgresql/16-main.pid
rm -f /var/run/postgresql/.s.PGSQL.*

# Ensure data directory permissions are correct (handles podman UID remapping)
chown -R postgres:postgres /var/lib/postgresql/16/main
chmod 700 /var/lib/postgresql/16/main

# Start PostgreSQL with -w (wait for startup) and 60s timeout
su -s /bin/sh postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/16/main -o '-c config_file=/etc/postgresql/16/main/postgresql.conf' -l /var/log/postgresql/pg.log -w -t 60 start" || {
    echo "pg_ctl start failed. Log:"
    cat /var/log/postgresql/pg.log 2>/dev/null || true
}

# Wait for PostgreSQL to accept connections
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then
        break
    fi
    sleep 1
done

exec "$@"
