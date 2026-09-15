#!/bin/bash
set -e

# Find PostgreSQL version
PG_VERSION=$(ls /etc/postgresql/)

# Configure trust authentication for local connections
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"
echo "local all all trust" > "$PG_HBA"
echo "host all all 127.0.0.1/32 trust" >> "$PG_HBA"
echo "host all all ::1/128 trust" >> "$PG_HBA"

# Ensure synchronous_commit is on for data durability
PG_CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
echo "synchronous_commit = on" >> "$PG_CONF"
echo "fsync = on" >> "$PG_CONF"
echo "full_page_writes = on" >> "$PG_CONF"

# Start PostgreSQL
pg_ctlcluster ${PG_VERSION} main start

# Wait for readiness
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then
        break
    fi
    sleep 1
done

# Verify PostgreSQL is ready
pg_isready || { echo "PostgreSQL failed to start"; exit 1; }

# Create user and database
psql -U postgres -c "CREATE ROLE auditor LOGIN SUPERUSER;"
psql -U postgres -c "CREATE DATABASE txstore OWNER auditor;"

# Generate and load data
python3 /tmp/generate_db.py

# Force checkpoint to flush all data to disk
psql -U auditor -d txstore -c "CHECKPOINT;"

# Verify data loaded correctly
echo "=== Final Verification ==="
OPS_COUNT=$(psql -U auditor -d txstore -t -A -c "SELECT COUNT(*) FROM operations;")
TX_COUNT=$(psql -U auditor -d txstore -t -A -c "SELECT COUNT(DISTINCT tx_id) FROM operations;")
OUT_COUNT=$(psql -U auditor -d txstore -t -A -c "SELECT COUNT(*) FROM tx_outcomes;")
MIXED=$(psql -U auditor -d txstore -t -A -c "SELECT COUNT(*) FROM (SELECT tx_id FROM tx_outcomes GROUP BY tx_id HAVING COUNT(DISTINCT outcome) > 1) sub;")
ABORTED=$(psql -U auditor -d txstore -t -A -c "SELECT COUNT(*) FROM tx_outcomes WHERE outcome = 'aborted';")

echo "Operations: ${OPS_COUNT}"
echo "Distinct transactions: ${TX_COUNT}"
echo "TX outcomes: ${OUT_COUNT}"
echo "Mixed-outcome transactions: ${MIXED}"
echo "Aborted outcomes: ${ABORTED}"

# Fail the build if data is incorrect
if [ "${OUT_COUNT}" -lt 2000 ]; then
    echo "ERROR: tx_outcomes too few (${OUT_COUNT}), expected ~2317"
    exit 1
fi

if [ "${MIXED}" -lt 2 ]; then
    echo "ERROR: Too few mixed-outcome transactions (${MIXED}), expected 2"
    exit 1
fi

if [ "${ABORTED}" -lt 3 ]; then
    echo "ERROR: Too few aborted outcomes (${ABORTED}), expected >= 3"
    exit 1
fi

echo "=== All verifications passed ==="

# Stop PostgreSQL cleanly - use fast mode and wait for full shutdown
pg_ctlcluster ${PG_VERSION} main stop -- -m fast

# Sync filesystem to ensure Docker layer captures all data
sync
