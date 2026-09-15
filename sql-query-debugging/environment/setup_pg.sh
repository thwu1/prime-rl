#!/bin/bash
set -e

# Configure trust authentication for local connections
PG_HBA=$(find /etc/postgresql -name pg_hba.conf | head -1)
sed -i 's/peer/trust/g; s/scram-sha-256/trust/g; s/md5/trust/g' "$PG_HBA"

# Determine PostgreSQL version and start the service
PG_VER=$(pg_lsclusters -h | awk '{print $1}')
pg_ctlcluster "$PG_VER" main start
sleep 2

# Create database
su - postgres -c "createdb trading"

# Load schema by piping content (avoids file permission issues with postgres user)
cat /app/pg_schema.sql | su - postgres -c "psql -d trading"

# Export each table from SQLite as CSV and import into PostgreSQL
for table in traders instruments trades daily_prices risk_limits; do
    sqlite3 -header -csv /app/trading.db "SELECT * FROM $table" > /tmp/${table}.csv
    chmod 644 /tmp/${table}.csv
    su - postgres -c "psql -d trading -c \"COPY $table FROM '/tmp/${table}.csv' WITH (FORMAT csv, HEADER true, NULL '')\""
done

# Clean up temp files
rm -f /tmp/*.csv

# Stop PostgreSQL (data persists on disk in the image layer)
pg_ctlcluster "$PG_VER" main stop
