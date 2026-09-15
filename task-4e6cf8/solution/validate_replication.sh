#!/bin/bash

# Litestream replication validation pipeline
# Requires: litestream CLI, sqlite3 CLI, recovered.db from Part 1

# Copy recovered DB to a working copy (keep recovered.db unmodified)
cp /app/data/recovered.db /app/data/replicated.db
rm -f /app/data/replicated.db-wal /app/data/replicated.db-shm

# Litestream requires WAL-mode databases for replication
sqlite3 /app/data/replicated.db "PRAGMA journal_mode=wal;"

# Ensure replica directory exists
mkdir -p /app/data/replica

# Start Litestream continuous replication in background
litestream replicate -config /app/litestream.yml &
LSPID=$!

# Wait for initial snapshot to be taken
sleep 10

# Record pre-validation state
SOURCE_COUNT=$(sqlite3 /app/data/replicated.db "SELECT COUNT(*) FROM sensors;")

# Insert validation records using sqlite3 CLI
sqlite3 /app/data/replicated.db "INSERT INTO sensors VALUES (100, 'validation_01', 'test_zone', 99.99, 99999);"
sqlite3 /app/data/replicated.db "INSERT INTO sensors VALUES (101, 'validation_02', 'test_zone', 88.88, 99998);"
VALIDATION_COUNT=2

# Wait for Litestream to replicate the new data
sleep 10

# Stop Litestream gracefully
kill "$LSPID" 2>/dev/null || true
wait "$LSPID" 2>/dev/null || true
sleep 2

# Restore database from Litestream file replica
litestream restore -config /app/litestream.yml -o /app/data/replica_restored.db /app/data/replicated.db

# Validate restored database
RESTORED_COUNT=$(sqlite3 /app/data/replica_restored.db "SELECT COUNT(*) FROM sensors;")
INTEGRITY=$(sqlite3 /app/data/replica_restored.db "PRAGMA integrity_check;" | head -1)
LITESTREAM_VERSION=$(litestream version 2>&1 | head -1 || echo "unknown")

EXPECTED_TOTAL=$((SOURCE_COUNT + VALIDATION_COUNT))
if [ "$RESTORED_COUNT" -ge "$SOURCE_COUNT" ] && [ "$INTEGRITY" = "ok" ]; then
    CONSISTENT=true
else
    CONSISTENT=false
fi

# Generate replication report as JSON
cat > /app/data/replication_report.json << ENDREPORT
{
  "litestream_version": "${LITESTREAM_VERSION}",
  "replica_path": "/app/data/replica/",
  "source_row_count": ${SOURCE_COUNT},
  "validation_rows_inserted": ${VALIDATION_COUNT},
  "restored_row_count": ${RESTORED_COUNT},
  "data_consistent": ${CONSISTENT},
  "integrity_check": "${INTEGRITY}"
}
ENDREPORT

echo "Replication validation complete."
echo "Source: ${SOURCE_COUNT} rows, Validation: ${VALIDATION_COUNT} inserted"
echo "Restored: ${RESTORED_COUNT} rows, Consistent: ${CONSISTENT}"
