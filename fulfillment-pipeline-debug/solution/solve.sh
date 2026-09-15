#!/bin/bash

set -e

# Set up PostgreSQL
PG_VER=$(ls /etc/postgresql/ | head -1)
PG_HBA="/etc/postgresql/$PG_VER/main/pg_hba.conf"
echo "local all all trust" > "$PG_HBA"
echo "host all all 127.0.0.1/32 trust" >> "$PG_HBA"
echo "host all all ::1/128 trust" >> "$PG_HBA"

pg_ctlcluster "$PG_VER" main start 2>/dev/null || true
sleep 2

# Create fresh database
psql -U postgres -c "DROP DATABASE IF EXISTS fulfillment_analytics" 2>/dev/null || true
psql -U postgres -c "CREATE DATABASE fulfillment_analytics"

# Load schema and data
psql -U postgres -d fulfillment_analytics -f /app/schema.sql -q
python3 /app/generate_data.py | psql -U postgres -d fulfillment_analytics -q

# Deploy the fixed analytics SQL
cp /solution/fixed_analytics.sql /app/analytics.sql

# Execute the fixed views
psql -U postgres -d fulfillment_analytics -f /app/analytics.sql
