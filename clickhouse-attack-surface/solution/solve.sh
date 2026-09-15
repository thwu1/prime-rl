#!/bin/bash

# Ensure PostgreSQL is running
if ! pg_isready -q 2>/dev/null; then
    PG_MAJOR=$(ls /etc/postgresql/ 2>/dev/null | sort -n | tail -1)
    if [ -z "$PG_MAJOR" ]; then
        PG_MAJOR=16
    fi
    pg_ctlcluster "$PG_MAJOR" main start
    for i in $(seq 1 60); do
        pg_isready -q 2>/dev/null && break
        sleep 1
    done
fi

if ! pg_isready -q 2>/dev/null; then
    echo "[FATAL] PostgreSQL did not start" >&2
    exit 1
fi

python3 /solution/exploit.py
