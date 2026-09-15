#!/bin/bash

# Start PostgreSQL if not already running
if ! pg_isready -q 2>/dev/null; then
    # Clean up stale PID and socket files
    rm -f /var/lib/postgresql/16/main/postmaster.pid
    rm -f /var/run/postgresql/16-main.pid
    rm -f /var/run/postgresql/.s.PGSQL.*

    # Ensure directories and permissions
    mkdir -p /var/run/postgresql && chown postgres:postgres /var/run/postgresql
    mkdir -p /var/log/postgresql && chown postgres:postgres /var/log/postgresql
    chown -R postgres:postgres /var/lib/postgresql/16/main
    chmod 700 /var/lib/postgresql/16/main

    # Start PostgreSQL with -w (wait for ready) and 60s timeout
    su -s /bin/sh postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/16/main -o '-c config_file=/etc/postgresql/16/main/postgresql.conf' -l /var/log/postgresql/pg.log -w -t 60 start" || true
fi

# Wait for PostgreSQL to accept connections
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then
        break
    fi
    sleep 1
done

# Verify PostgreSQL is running before proceeding
if ! pg_isready -q 2>/dev/null; then
    echo "ERROR: PostgreSQL failed to start"
    cat /var/log/postgresql/pg.log 2>/dev/null || true
    exit 1
fi

# Install dependencies
pip3 install psycopg2-binary==2.9.10 -q

# Run the repair pipeline
python3 /solution/repair.py
