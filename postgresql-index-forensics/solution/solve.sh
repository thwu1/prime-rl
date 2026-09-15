#!/bin/bash


# Start PostgreSQL if not already running
if ! pg_isready -q 2>/dev/null; then
    PG_VER=$(ls /etc/postgresql/ | head -1)
    pg_ctlcluster $PG_VER main start
    for i in $(seq 1 30); do
        if pg_isready -q 2>/dev/null; then
            break
        fi
        sleep 1
    done
fi

# Install solution dependencies
pip3 install psycopg2-binary==2.9.10 -q

# Run the analysis and migration tool
python3 /solution/analyze.py
