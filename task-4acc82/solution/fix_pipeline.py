#!/usr/bin/env python3

"""
Write the corrected pipeline.sh that fixes all 5 extraction bugs:

1. Case sensitivity: add -i flag (handles lowercase codes in app_events.log)
2. Hidden files: add --hidden flag (includes .app_errors.log)
3. Binary files: add -a flag (treats binary_mixed.log as text; note that
   --binary is NOT sufficient because it suppresses output from files
   detected as binary — -a/--text disables binary detection entirely)
4. Multiline: add -U flag and change single space to \\s+ (handles
   exceptions.log entries where code= and msg= are on separate lines)
5. Greedy quantifier: replace (.+) with ([^"]*) so message extraction
   stops at the first closing quote instead of the last one on the line

Additionally: normalize extracted error codes to uppercase before the
xsv join, since -i causes lowercase codes to be extracted verbatim and
the reference CSV uses uppercase keys.
"""

FIXED_PIPELINE = r'''#!/bin/bash
# Log analysis pipeline — corrected version
set -e

OUTPUT_DIR="/app/output"
mkdir -p "$OUTPUT_DIR"
TMP_DIR=$(mktemp -d)

# Step 1: Extract error code and message from ALL log files
# Flags:
#   -i           case-insensitive (handles lowercase codes like e001)
#   --hidden     include hidden dotfiles (.app_errors.log)
#   -a           treat binary files as text (binary_mixed.log); --binary
#                alone suppresses output from binary-detected files
#   -U           multiline mode so \s+ can cross line boundaries
# Pattern changes:
#   \s+ instead of single space (spans continuation lines)
#   [^"]* instead of .+ (non-greedy message capture)
rg -i -U --hidden -a \
   'code=([eE]\d{3})\s+msg="([^"]*)"' /app/logs/ \
   --no-filename -o -r '$1,$2' \
   > "$TMP_DIR/raw.csv"

# Step 2: Normalize error codes to uppercase and add CSV header
echo "error_code,message" > "$TMP_DIR/errors.csv"
awk -F, '{$1=toupper($1); print $1","$2}' "$TMP_DIR/raw.csv" \
   >> "$TMP_DIR/errors.csv"

# Step 3: Join with reference data to add category and severity
xsv join error_code "$TMP_DIR/errors.csv" \
   error_code /app/reference.csv \
   > "$TMP_DIR/joined.csv"

# Step 4: Aggregate and produce final results
python3 /app/aggregate.py "$TMP_DIR/joined.csv" "$OUTPUT_DIR/results.csv"

rm -rf "$TMP_DIR"
echo "Pipeline complete. Results written to $OUTPUT_DIR/results.csv"
'''

with open('/app/pipeline.sh', 'w') as f:
    f.write(FIXED_PIPELINE)
