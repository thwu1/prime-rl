#!/bin/bash

# Start PostgreSQL
PG_VER=$(pg_lsclusters -h | awk '{print $1}')
pg_ctlcluster "$PG_VER" main start
sleep 2
pg_isready || { echo "PostgreSQL failed to start"; exit 1; }

cd /app
python3 /solution/correct_queries.py

# Verify each fixed query runs on PostgreSQL
echo "Verifying fixed queries on PostgreSQL..."
for n in 1 2 3 4 5 6 7; do
    echo "--- Query $n ---"
    psql -d trading -U postgres -f /app/fixed_queries/query_${n}.sql 2>&1 | head -10
    echo ""
done

# Validate audit report with jq
echo "Validating audit report..."
jq '.' /app/audit_report.json > /dev/null && echo "Audit report is valid JSON"

echo "All queries written and verified."
