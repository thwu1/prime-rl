#!/bin/bash
# Runtime startup: just start PostgreSQL (all setup was done during build).
PG_VER=$(ls /etc/postgresql/ 2>/dev/null | head -1)
if [ -n "$PG_VER" ]; then
    rm -f "/var/run/postgresql/$PG_VER-main.pid" 2>/dev/null
    rm -f /var/run/postgresql/.s.PGSQL.5432* 2>/dev/null
    mkdir -p /var/run/postgresql
    chown postgres:postgres /var/run/postgresql
    pg_ctlcluster "$PG_VER" main start 2>/dev/null || true
    for i in $(seq 1 30); do
        pg_isready -q 2>/dev/null && break
        sleep 1
    done
fi
exec "$@"
