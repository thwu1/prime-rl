#!/bin/bash

PG_MAJOR=$(ls /etc/postgresql/ 2>/dev/null | sort -n | tail -1)
if [ -z "$PG_MAJOR" ]; then
    PG_MAJOR=16
fi

pg_ctlcluster "$PG_MAJOR" main start

for i in $(seq 1 60); do
    if pg_isready -q 2>/dev/null; then
        break
    fi
    sleep 1
done

touch /app/.init_complete

tail -f /dev/null
