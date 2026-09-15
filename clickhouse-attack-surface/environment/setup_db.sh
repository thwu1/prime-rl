#!/bin/bash
set -e

PG_MAJOR=$(ls /etc/postgresql/ 2>/dev/null | sort -n | tail -1)
if [ -z "$PG_MAJOR" ]; then
    PG_MAJOR=16
    pg_createcluster "$PG_MAJOR" main
fi

PG_DATA="/var/lib/postgresql/${PG_MAJOR}/main"
PG_CONF="/etc/postgresql/${PG_MAJOR}/main"

if [ ! -d "$PG_DATA" ]; then
    pg_createcluster "$PG_MAJOR" main
fi

# Trust auth during setup
echo "local all all trust" > "${PG_CONF}/pg_hba.conf"
echo "host all all 127.0.0.1/32 trust" >> "${PG_CONF}/pg_hba.conf"

pg_ctlcluster "$PG_MAJOR" main start

for i in $(seq 1 60); do
    if pg_isready -q 2>/dev/null; then
        break
    fi
    sleep 1
done

if ! pg_isready -q 2>/dev/null; then
    cat /var/log/postgresql/*.log 2>/dev/null || true
    exit 1
fi

psql -U postgres -f /tmp/init.sql

# Switch to md5 password auth
echo "local all all md5" > "${PG_CONF}/pg_hba.conf"
echo "host all all 127.0.0.1/32 md5" >> "${PG_CONF}/pg_hba.conf"
echo "host all all ::1/128 md5" >> "${PG_CONF}/pg_hba.conf"

pg_ctlcluster "$PG_MAJOR" main reload
sleep 1
pg_ctlcluster "$PG_MAJOR" main stop
