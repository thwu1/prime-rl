#!/bin/bash

# Copy the reference calculator into place
cp /solution/frtb_calculator.py /app/frtb_calculator.py

# Create run.sh — the pipeline that loads params into SQLite,
# runs computation, and validates output with jq
cat > /app/run.sh << 'RUNEOF'
#!/bin/bash
set -e

# ------------------------------------------------------------------
# Step 1: Load regulatory parameter TSV files into SQLite database
# ------------------------------------------------------------------
rm -f /app/parameters.db

# Import each TSV file as a table named after the file stem.
# sqlite3 .import auto-creates the table using the first row as columns.
for tsvfile in /app/reg_tables/*.tsv; do
    tablename=$(basename "$tsvfile" .tsv)
    printf '.mode tabs\n.import %s %s\n' "$tsvfile" "$tablename" | sqlite3 /app/parameters.db
done

# Create audit tables for intermediate computation results
sqlite3 /app/parameters.db "CREATE TABLE audit_buckets (risk_class TEXT, bucket_id TEXT, scenario TEXT, kb REAL, sb REAL);"
sqlite3 /app/parameters.db "CREATE TABLE audit_scenarios (risk_class TEXT, scenario TEXT, capital REAL);"

echo "SQLite database created with $(sqlite3 /app/parameters.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table';") tables"

# ------------------------------------------------------------------
# Step 2: Run FRTB capital calculation
# Reads parameters from SQLite, writes audit data back, outputs JSON
# ------------------------------------------------------------------
python3 /app/frtb_calculator.py

# ------------------------------------------------------------------
# Step 3: Validate output JSON schema with jq
# ------------------------------------------------------------------
if [ -f /app/output/capital_report.json ]; then
    jq -e '.delta.equity.medium and .delta.fx.medium and .delta.girr.medium and .delta.csr_nonsec.medium and .drc.equity and .scenario_totals.medium and .sbm_delta_capital and .total_capital' /app/output/capital_report.json > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Output JSON schema validation failed"
        exit 1
    fi
    echo "Output JSON schema validated with jq"
else
    echo "ERROR: /app/output/capital_report.json not found"
    exit 1
fi

# Verify audit data was written
AUDIT_COUNT=$(sqlite3 /app/parameters.db "SELECT COUNT(*) FROM audit_scenarios;")
echo "Audit scenarios recorded: $AUDIT_COUNT"
RUNEOF
chmod +x /app/run.sh

# Execute the pipeline
cd /app && bash /app/run.sh
