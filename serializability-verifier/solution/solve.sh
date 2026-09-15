#!/bin/bash

pip3 install psycopg2-binary==2.9.9 -q

# Start PostgreSQL
PG_VERSION=$(ls /etc/postgresql/)
pg_ctlcluster ${PG_VERSION} main start

# Wait for PostgreSQL to be fully ready
for i in $(seq 1 30); do
    if pg_isready -q 2>/dev/null; then
        break
    fi
    sleep 1
done

# Verify database is accessible
psql -U auditor -d txstore -c "SELECT 1;" > /dev/null 2>&1 || {
    echo "ERROR: Cannot connect to PostgreSQL database txstore"
    exit 1
}

# Diagnostic: verify data before analysis
echo "=== Pre-analysis data check ==="
psql -U auditor -d txstore -t -A -c "SELECT 'ops=' || COUNT(*) FROM operations;"
psql -U auditor -d txstore -t -A -c "SELECT 'outcomes=' || COUNT(*) FROM tx_outcomes;"
psql -U auditor -d txstore -t -A -c "SELECT 'mixed=' || COUNT(*) FROM (SELECT tx_id FROM tx_outcomes GROUP BY tx_id HAVING COUNT(DISTINCT outcome) > 1) sub;"

cd /app
python3 /solution/verifier.py
