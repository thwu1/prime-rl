#!/bin/bash
# Log analysis pipeline: extract error events, join with reference data, aggregate
set -e

OUTPUT_DIR="/app/output"
mkdir -p "$OUTPUT_DIR"
TMP_DIR=$(mktemp -d)

# Step 1: Extract error code and message from all log files
# Pattern: code=EXXX msg="..."
rg 'code=(E\d{3}) msg="(.+)"' /app/logs/ \
   --no-filename -o -r '$1,$2' \
   > "$TMP_DIR/raw.csv"

# Step 2: Prepare CSV with header
echo "error_code,message" > "$TMP_DIR/errors.csv"
cat "$TMP_DIR/raw.csv" >> "$TMP_DIR/errors.csv"

# Step 3: Join with reference data to add category and severity
xsv join error_code "$TMP_DIR/errors.csv" \
   error_code /app/reference.csv \
   > "$TMP_DIR/joined.csv"

# Step 4: Aggregate and produce final results
python3 /app/aggregate.py "$TMP_DIR/joined.csv" "$OUTPUT_DIR/results.csv"

rm -rf "$TMP_DIR"
echo "Pipeline complete. Results written to $OUTPUT_DIR/results.csv"
