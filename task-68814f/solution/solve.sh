#!/usr/bin/env bash

cd /app

# Inspect corrupted database with simdb-ctl
echo "=== Database info ==="
simdb-ctl info /app/data.db

# Examine WAL contents
echo ""
echo "=== WAL dump ==="
simdb-ctl wal-dump /app/wal.log

# Query backup schema
echo ""
echo "=== Backup tables ==="
sqlite3 /app/backup.sqlite ".tables"
echo ""
echo "=== DB config ==="
sqlite3 /app/backup.sqlite "SELECT * FROM db_config;"
echo ""
echo "=== WAL metadata (WARNING: may be inaccurate) ==="
sqlite3 /app/backup.sqlite "SELECT * FROM wal_metadata;"

# Run recovery
echo ""
echo "=== Running recovery ==="
python3 /solution/recover.py

# Validate result
echo ""
echo "=== Validation ==="
simdb-ctl validate /app/recovered.db
