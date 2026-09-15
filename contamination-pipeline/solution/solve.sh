#!/usr/bin/env bash

set -e

# Start PostgreSQL
pg_ctlcluster 16 main start

# Wait for PostgreSQL to become ready
for i in $(seq 1 15); do
    pg_isready -U postgres -q && break
    sleep 1
done

# Install solution dependencies
pip3 install psycopg2-binary==2.9.9 -q

# Run pipeline
python3 /solution/pipeline.py
