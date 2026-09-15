#!/bin/bash
# Run a strategy through the full pipeline and write results to a given path
# Usage: bash /app/run_strategy.sh /app/strategies/strategy_X.sh /path/to/output.csv
set -e

STRATEGY="$1"
OUTPUT="$2"

if [ -z "$STRATEGY" ] || [ -z "$OUTPUT" ]; then
    echo "Usage: $0 <strategy.sh> <output.csv>" >&2
    exit 1
fi

TMP_DIR=$(mktemp -d)

bash "$STRATEGY" > "$TMP_DIR/raw.csv" 2>/dev/null || true

echo "error_code,message" > "$TMP_DIR/errors.csv"
cat "$TMP_DIR/raw.csv" >> "$TMP_DIR/errors.csv"

xsv join error_code "$TMP_DIR/errors.csv" error_code /app/reference.csv > "$TMP_DIR/joined.csv"

mkdir -p "$(dirname "$OUTPUT")"
python3 /app/aggregate.py "$TMP_DIR/joined.csv" "$OUTPUT"

rm -rf "$TMP_DIR"
