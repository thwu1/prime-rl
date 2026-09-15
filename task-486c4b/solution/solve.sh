#!/bin/bash

pip3 install psycopg2-binary==2.9.10 -q

# Start PostgreSQL
pg_ctlcluster 16 main start
until pg_isready -U postgres -q; do sleep 1; done

# Run the optimization script
python3 /solution/optimize.py

# Apply the generated SQL to the database
psql -U postgres -d postgres_air -f /app/indexes.sql
psql -U postgres -d postgres_air -f /app/optimized_search.sql

# Update statistics after index creation
psql -U postgres -d postgres_air -c "ANALYZE"
