#!/bin/bash

# Install solution dependencies
pip3 install psycopg2-binary==2.9.10 -q

# Start PostgreSQL
pg_ctlcluster 16 main start
for i in $(seq 1 30); do
    pg_isready -U bench -d benchdb > /dev/null 2>&1 && break
    sleep 1
done

# Run the optimizer
python3 /solution/optimizer.py
