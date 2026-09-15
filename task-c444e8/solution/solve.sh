#!/bin/bash

# Ensure socket directory and start PostgreSQL
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql
service postgresql start 2>/dev/null || true
sleep 3

# Run the solution script
python3 /solution/fix_db.py
