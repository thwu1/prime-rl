#!/bin/bash

set -e

# Ensure PostgreSQL runtime directory exists
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql

# Start PostgreSQL if not already running
PG_VERSION=$(ls /etc/postgresql/ | head -1)
rm -f "/var/lib/postgresql/${PG_VERSION}/main/postmaster.pid" 2>/dev/null || true

if ! pg_isready -q 2>/dev/null; then
    pg_ctlcluster ${PG_VERSION} main start
    for i in $(seq 1 30); do
        if pg_isready -q 2>/dev/null; then break; fi
        sleep 1
    done
fi

pg_isready -q || { echo "PostgreSQL failed to start"; exit 1; }

# Ensure database exists and has data (fallback re-load if build-time data didn't persist)
if ! psql -U postgres -d alien_signals -c "SELECT 1" >/dev/null 2>&1; then
    createdb -U postgres alien_signals 2>/dev/null || true
    psql -U postgres -d alien_signals -f /app/init.sql
else
    ROW_COUNT=$(psql -U postgres -d alien_signals -t -A -c "SELECT COUNT(*) FROM signals;" 2>/dev/null || echo "0")
    if [ "${ROW_COUNT}" -lt 1 ] 2>/dev/null; then
        psql -U postgres -d alien_signals -f /app/init.sql
    fi
fi

# Run pipeline SQL to create functions, view, trigger
psql -U postgres -d alien_signals -f /solution/solve_pipeline.sql

# Export materialized view to CSV
psql -U postgres -d alien_signals -c "COPY (SELECT * FROM mv_signal_analysis ORDER BY signalregistry) TO STDOUT WITH CSV HEADER" > /app/signal_report.csv
